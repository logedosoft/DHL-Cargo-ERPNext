# Copyright (c) 2026, Logedosoft Business Solutions and contributors
# For license information, please see license.txt

import frappe
from unittest.mock import patch, MagicMock
from dhl_ecommerce_integration.utils import _sync_barcode_rows, _make_piece_barcode

FRAPPE_INTERNALS = {"name", "parent", "parenttype", "parentfield", "idx", "doctype", "creation", "modified", "modified_by", "owner", "docstatus", "db_insert"}
ALLOWED_FIELDS = {"piece_number", "barcode_zpl", "barcode", "desi", "kg"}


def _make_barcodes(lstEntries):
	return [{"pieceNumber": n, "value": "^XA piece{0} ^XZ".format(n)} for n in lstEntries]


def _make_parcels(lstDimensions):
	return [{"desi": d, "kg": k} for d, k in lstDimensions]


def _make_preexisting_row(dDesi, dKg, strName=None):
	dctRow = frappe._dict({"desi": dDesi, "kg": dKg})
	if strName:
		dctRow.name = strName
	return dctRow


def _assert_no_phantom_fields(lstRows):
	for dctRow in lstRows:
		lstUserKeys = [k for k in dctRow if k not in FRAPPE_INTERNALS]
		assert ALLOWED_FIELDS.issuperset(lstUserKeys), "Phantom fields found: {0}".format(
			set(lstUserKeys) - ALLOWED_FIELDS
		)


def test_reuse_path_three_preexisting_rows():
	lstRows = [
		_make_preexisting_row(2, 3, "DN-TEST001-DHL-001"),
		_make_preexisting_row(5, 8, "DN-TEST001-DHL-002"),
		_make_preexisting_row(1, 1, "DN-TEST001-DHL-003"),
	]
	lstBarcodes = _make_barcodes([1, 2, 3])
	lstParcels = _make_parcels([(2, 3), (5, 8), (1, 1)])
	frappe.flags.in_test = True

	with patch("dhl_ecommerce_integration.utils.frappe.db.set_value") as mockSetVal:
		dctResult = _sync_barcode_rows(lstRows, lstBarcodes, lstParcels, "DN-TEST001")
		assert mockSetVal.call_count == 3

	assert dctResult.op_result is True
	assert dctResult.synced_count == 3
	assert len(lstRows) == 3
	for dIdx in range(3):
		dctRow = lstRows[dIdx]
		assert dctRow.piece_number == dIdx + 1
		assert dctRow.barcode_zpl == "^XA piece{0} ^XZ".format(dIdx + 1)
		assert dctRow.barcode == _make_piece_barcode("DN-TEST001", dIdx + 1, 3)
		assert dctRow.desi == lstParcels[dIdx]["desi"]
		assert dctRow.kg == lstParcels[dIdx]["kg"]
	_assert_no_phantom_fields(lstRows)


def _make_mock_doc(strName):
	dctDoc = frappe._dict()
	dctDoc.name = strName
	dctDoc.db_insert = MagicMock()
	return dctDoc


def test_no_preexisting_rows_append():
	lstRows = []
	lstBarcodes = _make_barcodes([1, 2, 3])
	lstParcels = _make_parcels([(4, 5), (6, 7), (8, 9)])
	frappe.flags.in_test = True

	lstMockDocs = [
		_make_mock_doc("DN-TEST002-DHL-NEW-1"),
		_make_mock_doc("DN-TEST002-DHL-NEW-2"),
		_make_mock_doc("DN-TEST002-DHL-NEW-3"),
	]

	with patch("dhl_ecommerce_integration.utils.frappe.new_doc", side_effect=lstMockDocs):
		dctResult = _sync_barcode_rows(lstRows, lstBarcodes, lstParcels, "DN-TEST002")

	assert dctResult.op_result is True
	assert dctResult.synced_count == 3
	assert len(lstRows) == 3
	assert lstRows[0].piece_number == 1
	assert lstRows[0].desi == 4
	assert lstRows[0].kg == 5
	assert lstRows[2].piece_number == 3
	assert lstRows[2].desi == 8
	assert lstRows[2].kg == 9
	for dI in range(3):
		lstMockDocs[dI].db_insert.assert_called_once()
	_assert_no_phantom_fields(lstRows)


def test_idempotency_no_duplicates():
	lstRows = [
		_make_preexisting_row(2, 3, "DN-TEST003-DHL-001"),
		_make_preexisting_row(5, 8, "DN-TEST003-DHL-002"),
	]
	lstBarcodes = _make_barcodes([1, 2])
	lstParcels = _make_parcels([(2, 3), (5, 8)])
	frappe.flags.in_test = True

	with patch("dhl_ecommerce_integration.utils.frappe.db.set_value") as mockSetVal:
		dctResult1 = _sync_barcode_rows(lstRows, lstBarcodes, lstParcels, "DN-TEST003")
		assert mockSetVal.call_count == 2

	assert dctResult1.op_result is True
	assert dctResult1.synced_count == 2
	assert len(lstRows) == 2

	with patch("dhl_ecommerce_integration.utils.frappe.db.set_value") as mockSetVal:
		dctResult2 = _sync_barcode_rows(lstRows, lstBarcodes, lstParcels, "DN-TEST003")
		assert mockSetVal.call_count == 2

	assert dctResult2.op_result is True
	assert dctResult2.synced_count == 2
	assert len(lstRows) == 2
	assert lstRows[0].barcode_zpl == "^XA piece1 ^XZ"
	assert lstRows[1].barcode_zpl == "^XA piece2 ^XZ"
	_assert_no_phantom_fields(lstRows)


def test_stale_row_cleanup():
	lstRows = [
		_make_preexisting_row(1, 1, "DN-TEST004-DHL-001"),
		_make_preexisting_row(2, 2, "DN-TEST004-DHL-002"),
		_make_preexisting_row(3, 3, "DN-TEST004-DHL-003"),
		_make_preexisting_row(4, 4, "DN-TEST004-DHL-004"),
	]
	lstBarcodes = _make_barcodes([1, 2])
	lstParcels = _make_parcels([(10, 11), (12, 13)])
	frappe.flags.in_test = True

	with patch("dhl_ecommerce_integration.utils.frappe.db.set_value"), \
		patch("dhl_ecommerce_integration.utils.frappe.db.delete") as mockDelete:
		dctResult = _sync_barcode_rows(lstRows, lstBarcodes, lstParcels, "DN-TEST004")
		assert mockDelete.call_count == 2

	assert dctResult.op_result is True
	assert dctResult.synced_count == 2
	assert len(lstRows) == 2
	assert lstRows[0].desi == 10
	assert lstRows[1].desi == 12
	_assert_no_phantom_fields(lstRows)


def test_single_piece_regression():
	lstRows = [_make_preexisting_row(3, 7, "DN-TEST005-DHL-001")]
	lstBarcodes = _make_barcodes([1])
	lstParcels = _make_parcels([(3, 7)])
	frappe.flags.in_test = True

	with patch("dhl_ecommerce_integration.utils.frappe.db.set_value"):
		dctResult = _sync_barcode_rows(lstRows, lstBarcodes, lstParcels, "DN-TEST005")

	assert dctResult.op_result is True
	assert dctResult.synced_count == 1
	assert len(lstRows) == 1
	assert lstRows[0].piece_number == 1
	assert lstRows[0].barcode == "DN-TEST005"
	assert lstRows[0].barcode_zpl == "^XA piece1 ^XZ"
	_assert_no_phantom_fields(lstRows)


def test_partial_presence_append_new():
	lstRows = [
		_make_preexisting_row(1, 2, "DN-TEST006-DHL-001"),
		_make_preexisting_row(3, 4, "DN-TEST006-DHL-002"),
	]
	lstBarcodes = _make_barcodes([1, 2, 3])
	lstParcels = _make_parcels([(10, 20), (30, 40), (50, 60)])
	frappe.flags.in_test = True

	objMockNew = _make_mock_doc("DN-TEST006-DHL-NEW")

	with patch("dhl_ecommerce_integration.utils.frappe.db.set_value") as mockSetVal, \
		patch("dhl_ecommerce_integration.utils.frappe.new_doc", return_value=objMockNew):
		dctResult = _sync_barcode_rows(lstRows, lstBarcodes, lstParcels, "DN-TEST006")
		assert mockSetVal.call_count == 2
		objMockNew.db_insert.assert_called_once()

	assert dctResult.op_result is True
	assert dctResult.synced_count == 3
	assert len(lstRows) == 3
	assert lstRows[0].desi == 10
	assert lstRows[0].piece_number == 1
	assert lstRows[1].desi == 30
	assert lstRows[1].piece_number == 2
	assert lstRows[2].desi == 50
	assert lstRows[2].piece_number == 3
	_assert_no_phantom_fields(lstRows)


def test_no_phantom_fields_after_sync():
	lstRows = []
	lstBarcodes = _make_barcodes([1, 2, 3])
	lstParcels = _make_parcels([(2, 3), (5, 8), (1, 1)])
	frappe.flags.in_test = True

	lstMockDocs = [
		_make_mock_doc("DN-TEST007-DHL-NEW-1"),
		_make_mock_doc("DN-TEST007-DHL-NEW-2"),
		_make_mock_doc("DN-TEST007-DHL-NEW-3"),
	]

	with patch("dhl_ecommerce_integration.utils.frappe.new_doc", side_effect=lstMockDocs):
		_sync_barcode_rows(lstRows, lstBarcodes, lstParcels, "DN-TEST007")

	assert len(lstRows) == 3
	_assert_no_phantom_fields(lstRows)
	for dctRow in lstRows:
		assert "barcode_zpl" in dctRow
		assert "barcode" in dctRow
		assert "piece_number" in dctRow
		assert "desi" in dctRow
		assert "kg" in dctRow
		assert "reference_id" not in dctRow
		assert "zpl" not in dctRow
		assert "attachment" not in dctRow
