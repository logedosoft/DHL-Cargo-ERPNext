# Copyright (c) 2026, Logedosoft Business Solutions and contributors
# For license information, please see license.txt

import frappe
from unittest.mock import patch, MagicMock
from dhl_ecommerce_integration.utils import _delete_stale_label_files, _generate_pdfs_for_dn


def test_delete_stale_filter_shape():
	lstCaptured = []

	def _mock_get_all(dt, filters=None, pluck=None):
		lstCaptured.append({"doctype": dt, "filters": filters, "pluck": pluck})
		return []

	with patch("dhl_ecommerce_integration.utils.frappe.get_all", side_effect=_mock_get_all):
		_delete_stale_label_files("DN-TEST001")

	assert len(lstCaptured) == 1
	dctCall = lstCaptured[0]
	assert dctCall["doctype"] == "File"
	assert dctCall["pluck"] == "name"
	assert dctCall["filters"]["attached_to_doctype"] == "Delivery Note"
	assert dctCall["filters"]["attached_to_name"] == "DN-TEST001"
	assert "DHL_Etiketi_DN-TEST001_%" == dctCall["filters"]["file_name"][1]


def test_delete_happy_path_three_files():
	lstDeleted = []

	def _mock_get_all(dt, filters=None, pluck=None):
		return ["File-001", "File-002", "File-003"]

	def _mock_delete_doc(dt, name, ignore_permissions=False):
		lstDeleted.append(name)

	with patch("dhl_ecommerce_integration.utils.frappe.get_all", side_effect=_mock_get_all), \
		patch("dhl_ecommerce_integration.utils.frappe.delete_doc", side_effect=_mock_delete_doc):
		dctResult = _delete_stale_label_files("DN-TEST002")

	assert dctResult.op_result is True
	assert dctResult.intDeleted == 3
	assert lstDeleted == ["File-001", "File-002", "File-003"]


def test_delete_one_failure_others_proceed():
	lstDeleted = []

	def _mock_get_all(dt, filters=None, pluck=None):
		return ["File-001", "File-002", "File-003"]

	def _mock_delete_doc(dt, name, ignore_permissions=False):
		if name == "File-002":
			raise Exception("simulated failure")
		lstDeleted.append(name)

	with patch("dhl_ecommerce_integration.utils.frappe.get_all", side_effect=_mock_get_all), \
		patch("dhl_ecommerce_integration.utils.frappe.delete_doc", side_effect=_mock_delete_doc), \
		patch("dhl_ecommerce_integration.utils.frappe.log_error") as mockLog:
		dctResult = _delete_stale_label_files("DN-TEST003")

	assert dctResult.op_result is True
	assert dctResult.intDeleted == 2
	assert lstDeleted == ["File-001", "File-003"]
	assert "File-002" in dctResult.op_message
	mockLog.assert_called()


def test_conversion_failure_blocks_everything():
	def _mock_convert(lstZpl):
		if "p2" in lstZpl[0]:
			return None
		return b"%PDF-1.4 fake content"

	def _mock_delete_stale(strDNName):
		raise Exception("_delete_stale_label_files must NOT be called on conversion failure")

	def _mock_attach(strDNName, bytPdf, strFileName):
		raise Exception("_attach_pdf_to_dn must NOT be called on conversion failure")

	lstDocs = [MagicMock(piece_number=1, barcode_zpl="^XA p1 ^XZ"),
		MagicMock(piece_number=2, barcode_zpl="^XA p2 ^XZ"),
		MagicMock(piece_number=3, barcode_zpl="^XA p3 ^XZ")]

	def _mock_get_doc(dt, name):
		dctDoc = MagicMock()
		dctDoc.dhl_barcodes = lstDocs
		return dctDoc

	with patch("dhl_ecommerce_integration.utils.frappe.get_doc", side_effect=_mock_get_doc), \
		patch("dhl_ecommerce_integration.utils._convert_zpl_to_pdf", side_effect=_mock_convert), \
		patch("dhl_ecommerce_integration.utils._delete_stale_label_files", side_effect=_mock_delete_stale), \
		patch("dhl_ecommerce_integration.utils._attach_pdf_to_dn", side_effect=_mock_attach):
		dctResult = _generate_pdfs_for_dn("DN-TEST004")

	assert dctResult.op_result is False
	assert "2" in dctResult.op_message
	assert len(dctResult.lst_file_urls) == 0


def test_full_success_three_pieces_ordering():
	lstCallLog = []

	def _mock_convert(lstZpl):
		lstCallLog.append(("convert", lstZpl[0]))
		return b"%PDF-1.4 fake content"

	def _mock_delete_stale(strDNName):
		lstCallLog.append(("delete", strDNName))
		return frappe._dict({"op_result": True, "op_message": "", "intDeleted": 2})

	def _mock_attach(strDNName, bytPdf, strFileName):
		lstCallLog.append(("attach", strFileName))
		return "/files/{0}".format(strFileName)

	lstDocs = [MagicMock(piece_number=1, barcode_zpl="^XA p1 ^XZ"),
		MagicMock(piece_number=2, barcode_zpl="^XA p2 ^XZ"),
		MagicMock(piece_number=3, barcode_zpl="^XA p3 ^XZ")]

	def _mock_get_doc(dt, name):
		dctDoc = MagicMock()
		dctDoc.dhl_barcodes = lstDocs
		return dctDoc

	with patch("dhl_ecommerce_integration.utils.frappe.get_doc", side_effect=_mock_get_doc), \
		patch("dhl_ecommerce_integration.utils._convert_zpl_to_pdf", side_effect=_mock_convert), \
		patch("dhl_ecommerce_integration.utils._delete_stale_label_files", side_effect=_mock_delete_stale), \
		patch("dhl_ecommerce_integration.utils._attach_pdf_to_dn", side_effect=_mock_attach):
		dctResult = _generate_pdfs_for_dn("DN-TEST005")

	assert dctResult.op_result is True
	assert len(dctResult.lst_file_urls) == 3
	assert dctResult.int_deleted == 2
	assert lstCallLog[0] == ("convert", "^XA p1 ^XZ")
	assert lstCallLog[1] == ("convert", "^XA p2 ^XZ")
	assert lstCallLog[2] == ("convert", "^XA p3 ^XZ")
	assert lstCallLog[3] == ("delete", "DN-TEST005")
	assert lstCallLog[4] == ("attach", "DHL_Etiketi_DN-TEST005_Parca1.pdf")
	assert lstCallLog[5] == ("attach", "DHL_Etiketi_DN-TEST005_Parca2.pdf")
	assert lstCallLog[6] == ("attach", "DHL_Etiketi_DN-TEST005_Parca3.pdf")


def test_empty_barcode_zpl_rows_skipped():
	def _mock_convert(lstZpl):
		raise Exception("_convert_zpl_to_pdf must NOT be called for empty barcode_zpl")

	def _mock_delete_stale(strDNName):
		raise Exception("_delete_stale_label_files must NOT be called when all rows empty")

	def _mock_attach(strDNName, bytPdf, strFileName):
		raise Exception("_attach_pdf_to_dn must NOT be called when all rows empty")

	lstDocs = [MagicMock(piece_number=1, barcode_zpl=""),
		MagicMock(piece_number=2, barcode_zpl=None),
		MagicMock(piece_number=3, barcode_zpl="")]

	def _mock_get_doc(dt, name):
		dctDoc = MagicMock()
		dctDoc.dhl_barcodes = lstDocs
		return dctDoc

	with patch("dhl_ecommerce_integration.utils.frappe.get_doc", side_effect=_mock_get_doc), \
		patch("dhl_ecommerce_integration.utils._convert_zpl_to_pdf", side_effect=_mock_convert), \
		patch("dhl_ecommerce_integration.utils._delete_stale_label_files", side_effect=_mock_delete_stale), \
		patch("dhl_ecommerce_integration.utils._attach_pdf_to_dn", side_effect=_mock_attach):
		dctResult = _generate_pdfs_for_dn("DN-TEST006")

	assert dctResult.op_result is False
	assert dctResult.op_message == "PDF generation failed"
	assert len(dctResult.lst_file_urls) == 0
