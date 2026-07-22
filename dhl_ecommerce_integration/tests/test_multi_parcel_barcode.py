# Copyright (c) 2026, Logedosoft Business Solutions and contributors
# For license information, please see license.txt

import frappe
from dhl_ecommerce_integration.utils import (
	_make_piece_barcode,
	_build_create_barcode_payload,
)


def test_single_piece_returns_plain_reference():
	strRef = "DN-00123"
	strResult = _make_piece_barcode(strRef, 1, 1)
	frappe.flags.in_test = True
	assert strResult == strRef, "Single parcel must return plain referenceId without suffix"


def test_multi_piece_zero_padded():
	strRef = "DN-00123"
	assert _make_piece_barcode(strRef, 1, 3) == "DN-00123-01"
	assert _make_piece_barcode(strRef, 2, 3) == "DN-00123-02"
	assert _make_piece_barcode(strRef, 3, 3) == "DN-00123-03"


def test_max_length_zero_padded_exceeded():
	strRef = "DN-VERYLONGREFERENCECODE28XX"
	assert len(strRef) + 3 > 30, "Test precondition: ref + -01 must exceed 30"
	strResult = _make_piece_barcode(strRef, 1, 3)
	assert len(strResult) <= 30, "Output must never exceed 30 chars"


def test_max_length_single_digit_fallback():
	strRef = "DN-VERYLONGREFERENCECODE28XX"
	assert len(strRef) + 2 <= 30, "Single-digit suffix must fit"
	strResult = _make_piece_barcode(strRef, 1, 3)
	assert len(strResult) <= 30, "Output must never exceed 30 chars"
	assert "-" in strResult, "Must contain a separator"


def test_max_length_truncation():
	strRef = "DN-ABSOLUTELYVERYLONGREFERENCEID2"
	assert len(strRef) + 2 > 30, "Even single-digit suffix must exceed 30"
	strResult = _make_piece_barcode(strRef, 1, 3)
	assert len(strResult) <= 30, "Output must never exceed 30 chars after truncation"
	assert strResult.endswith("-1"), "Must end with single-digit suffix after truncation"


def test_build_barcode_payload_multi_piece():
	strRef = "DN-TEST001"
	lstParcels = [
		{"desi": 2, "kg": 3},
		{"desi": 5, "kg": 8},
		{"desi": 1, "kg": 1},
	]
	dctPayload = _build_create_barcode_payload(strRef, lstParcels, "TEXTILE")
	lstPieceList = dctPayload["orderPieceList"]
	assert len(lstPieceList) == 3, "Must have 3 pieces"
	assert lstPieceList[0]["barcode"] == "DN-TEST001-01"
	assert lstPieceList[1]["barcode"] == "DN-TEST001-02"
	assert lstPieceList[2]["barcode"] == "DN-TEST001-03"
	assert lstPieceList[0]["barcode"] != lstPieceList[1]["barcode"]
	assert lstPieceList[1]["barcode"] != lstPieceList[2]["barcode"]


def test_build_barcode_payload_single_piece():
	strRef = "DN-TEST001"
	lstParcels = [{"desi": 2, "kg": 3}]
	dctPayload = _build_create_barcode_payload(strRef, lstParcels, "TEXTILE")
	lstPieceList = dctPayload["orderPieceList"]
	assert len(lstPieceList) == 1
	assert lstPieceList[0]["barcode"] == "DN-TEST001", "Single parcel must not have suffix"


def test_build_barcode_payload_preserves_desi_kg():
	strRef = "DN-TEST001"
	lstParcels = [
		{"desi": 10, "kg": 20},
		{"desi": 30, "kg": 40},
	]
	dctPayload = _build_create_barcode_payload(strRef, lstParcels, "TEXTILE")
	assert dctPayload["orderPieceList"][0]["desi"] == 10
	assert dctPayload["orderPieceList"][0]["kg"] == 20
	assert dctPayload["orderPieceList"][1]["desi"] == 30
	assert dctPayload["orderPieceList"][1]["kg"] == 40
