# Copyright (c) 2026, Logedosoft Business Solutions and contributors
# For license information, please see license.txt

import frappe
from dhl_ecommerce_integration.utils import _sync_barcode_rows, _make_piece_barcode


def _make_barcodes(lstEntries):
	return [{"pieceNumber": n, "value": "^XA piece{0} ^XZ".format(n)} for n in lstEntries]


def _make_parcels(lstDimensions):
	return [{"desi": d, "kg": k} for d, k in lstDimensions]


def _make_preexisting_row(dDesi, dKg):
	return frappe._dict({"desi": dDesi, "kg": dKg})


def test_reuse_path_three_preexisting_rows():
	lstRows = [_make_preexisting_row(2, 3), _make_preexisting_row(5, 8), _make_preexisting_row(1, 1)]
	lstBarcodes = _make_barcodes([1, 2, 3])
	lstParcels = _make_parcels([(2, 3), (5, 8), (1, 1)])
	frappe.flags.in_test = True

	dctResult = _sync_barcode_rows(lstRows, lstBarcodes, lstParcels, "DN-TEST001")

	assert dctResult.op_result is True
	assert dctResult.synced_count == 3
	assert len(lstRows) == 3
	for dIdx in range(3):
		dctRow = lstRows[dIdx]
		assert dctRow.piece_number == dIdx + 1
		assert dctRow.zpl == "^XA piece{0} ^XZ".format(dIdx + 1)
		assert dctRow.barcode == _make_piece_barcode("DN-TEST001", dIdx + 1, 3)
		assert dctRow.attachment == "APPENDED"
		assert dctRow.reference_id == "DN-TEST001"
		assert dctRow.desi == lstParcels[dIdx]["desi"]
		assert dctRow.kg == lstParcels[dIdx]["kg"]


def test_no_preexisting_rows_append():
	lstRows = []
	lstBarcodes = _make_barcodes([1, 2, 3])
	lstParcels = _make_parcels([(4, 5), (6, 7), (8, 9)])
	frappe.flags.in_test = True

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


def test_idempotency_no_duplicates():
	lstRows = [_make_preexisting_row(2, 3), _make_preexisting_row(5, 8)]
	lstBarcodes = _make_barcodes([1, 2])
	lstParcels = _make_parcels([(2, 3), (5, 8)])
	frappe.flags.in_test = True

	dctResult1 = _sync_barcode_rows(lstRows, lstBarcodes, lstParcels, "DN-TEST003")
	assert dctResult1.op_result is True
	assert dctResult1.synced_count == 2
	assert len(lstRows) == 2

	dctResult2 = _sync_barcode_rows(lstRows, lstBarcodes, lstParcels, "DN-TEST003")
	assert dctResult2.op_result is True
	assert dctResult2.synced_count == 2
	assert len(lstRows) == 2
	assert lstRows[0].zpl == "^XA piece1 ^XZ"
	assert lstRows[1].zpl == "^XA piece2 ^XZ"


def test_stale_row_cleanup():
	lstRows = [
		_make_preexisting_row(1, 1),
		_make_preexisting_row(2, 2),
		_make_preexisting_row(3, 3),
		_make_preexisting_row(4, 4),
	]
	lstBarcodes = _make_barcodes([1, 2])
	lstParcels = _make_parcels([(10, 11), (12, 13)])
	frappe.flags.in_test = True

	dctResult = _sync_barcode_rows(lstRows, lstBarcodes, lstParcels, "DN-TEST004")

	assert dctResult.op_result is True
	assert dctResult.synced_count == 2
	assert len(lstRows) == 2
	assert lstRows[0].desi == 10
	assert lstRows[1].desi == 12


def test_single_piece_regression():
	lstRows = [_make_preexisting_row(3, 7)]
	lstBarcodes = _make_barcodes([1])
	lstParcels = _make_parcels([(3, 7)])
	frappe.flags.in_test = True

	dctResult = _sync_barcode_rows(lstRows, lstBarcodes, lstParcels, "DN-TEST005")

	assert dctResult.op_result is True
	assert dctResult.synced_count == 1
	assert len(lstRows) == 1
	assert lstRows[0].piece_number == 1
	assert lstRows[0].attachment == "APPENDED"
	assert lstRows[0].barcode == "DN-TEST005"


def test_partial_presence_append_new():
	lstRows = [_make_preexisting_row(1, 2), _make_preexisting_row(3, 4)]
	lstBarcodes = _make_barcodes([1, 2, 3])
	lstParcels = _make_parcels([(10, 20), (30, 40), (50, 60)])
	frappe.flags.in_test = True

	dctResult = _sync_barcode_rows(lstRows, lstBarcodes, lstParcels, "DN-TEST006")

	assert dctResult.op_result is True
	assert dctResult.synced_count == 3
	assert len(lstRows) == 3
	assert lstRows[0].desi == 10
	assert lstRows[0].piece_number == 1
	assert lstRows[1].desi == 30
	assert lstRows[1].piece_number == 2
	assert lstRows[2].desi == 50
	assert lstRows[2].piece_number == 3
	assert lstRows[2].attachment == "APPENDED"
