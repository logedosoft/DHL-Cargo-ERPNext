# Copyright (c) 2026, Logedosoft Business Solutions and contributors
# For license information, please see license.txt

import frappe
from dhl_ecommerce_integration.utils import _flatten_barcode_elements


def _make_element(strRef, strInvoice, strShipment, lstBarcodes):
	return {
		"referenceId": strRef,
		"invoiceId": strInvoice,
		"shipmentId": strShipment,
		"barcodes": lstBarcodes,
	}


def _make_barcode(dPieceNumber, strValue):
	return {"pieceNumber": dPieceNumber, "value": strValue}


def test_three_elements_flat_list():
	lstData = [
		_make_element("SBX1785492139", "FM381358", "369845765006", [_make_barcode(1, "^XA piece1 ^XZ")]),
		_make_element("SBX1785492139", "FM381358", "369845765006", [_make_barcode(2, "^XA piece2 ^XZ")]),
		_make_element("SBX1785492139", "FM381358", "369845765006", [_make_barcode(3, "^XA piece3 ^XZ")]),
	]
	dctResult = _flatten_barcode_elements(lstData)
	frappe.flags.in_test = True

	assert dctResult.op_result is True
	assert dctResult.invoice_id == "FM381358"
	assert dctResult.shipment_id == "369845765006"
	assert len(dctResult.barcodes) == 3
	assert dctResult.barcodes[0]["pieceNumber"] == 1
	assert dctResult.barcodes[1]["pieceNumber"] == 2
	assert dctResult.barcodes[2]["pieceNumber"] == 3
	assert dctResult.barcodes[0]["value"] == "^XA piece1 ^XZ"
	assert dctResult.barcodes[1]["value"] == "^XA piece2 ^XZ"
	assert dctResult.barcodes[2]["value"] == "^XA piece3 ^XZ"


def test_single_element_single_barcode():
	lstData = [
		_make_element("DN-TEST001", "INV001", "SHIP001", [_make_barcode(1, "^XA solo ^XZ")]),
	]
	dctResult = _flatten_barcode_elements(lstData)
	frappe.flags.in_test = True

	assert dctResult.op_result is True
	assert dctResult.invoice_id == "INV001"
	assert dctResult.shipment_id == "SHIP001"
	assert len(dctResult.barcodes) == 1
	assert dctResult.barcodes[0]["pieceNumber"] == 1


def test_empty_barcodes_skipped_others_still_processed():
	lstData = [
		_make_element("REF001", "INV001", "SHIP001", []),
		_make_element("REF001", "INV001", "SHIP001", [_make_barcode(2, "^XA p2 ^XZ")]),
		_make_element("REF001", "INV001", "SHIP001", [_make_barcode(3, "^XA p3 ^XZ")]),
	]
	dctResult = _flatten_barcode_elements(lstData)
	frappe.flags.in_test = True

	assert dctResult.op_result is True
	assert len(dctResult.barcodes) == 2
	assert dctResult.barcodes[0]["pieceNumber"] == 2
	assert dctResult.barcodes[1]["pieceNumber"] == 3


def test_all_elements_empty_barcodes_yields_failure():
	lstData = [
		_make_element("REF001", "INV001", "SHIP001", []),
		_make_element("REF001", "INV001", "SHIP001", []),
	]
	dctResult = _flatten_barcode_elements(lstData)
	frappe.flags.in_test = True

	assert dctResult.op_result is False
	assert "no piece barcodes" in dctResult.op_message
	assert len(dctResult.barcodes) == 0


def test_missing_barcodes_key_treated_as_empty():
	lstData = [
		{"referenceId": "REF001", "invoiceId": "INV001", "shipmentId": "SHIP001"},
	]
	dctResult = _flatten_barcode_elements(lstData)
	frappe.flags.in_test = True

	assert dctResult.op_result is False
	assert "no piece barcodes" in dctResult.op_message


def test_non_list_response_yields_failure():
	dctResult = _flatten_barcode_elements("unexpected string")
	frappe.flags.in_test = True

	assert dctResult.op_result is False
	assert "Unexpected response format" in dctResult.op_message


def test_empty_list_yields_failure():
	dctResult = _flatten_barcode_elements([])
	frappe.flags.in_test = True

	assert dctResult.op_result is False
	assert "Unexpected response format" in dctResult.op_message


def test_defensive_multiple_barcodes_per_element():
	lstData = [
		_make_element("REF001", "INV001", "SHIP001", [
			_make_barcode(1, "^XA p1 ^XZ"),
			_make_barcode(2, "^XA p2 ^XZ"),
		]),
		_make_element("REF001", "INV001", "SHIP001", [
			_make_barcode(3, "^XA p3 ^XZ"),
		]),
	]
	dctResult = _flatten_barcode_elements(lstData)
	frappe.flags.in_test = True

	assert dctResult.op_result is True
	assert len(dctResult.barcodes) == 3
	assert dctResult.barcodes[0]["pieceNumber"] == 1
	assert dctResult.barcodes[1]["pieceNumber"] == 2
	assert dctResult.barcodes[2]["pieceNumber"] == 3
