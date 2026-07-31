# Copyright (c) 2026, Logedosoft Business Solutions and contributors
# For license information, please see license.txt

import re
import frappe, json, requests, base64, time
from datetime import datetime, timedelta, timezone
from frappe import msgprint, _
from frappe.utils import get_datetime_str
from urllib.parse import quote

# Helper function to convert Turkish characters to uppercase for DHL city-district maps
def uppercase_tr(s):
	if not s:
		return ""

	# 1. Translate specific Turkish lowercase letters to uppercase
	tr = str.maketrans("ıişüğçö", "IİŞÜĞÇÖ")

	# 2. Apply translation, then standard upper() for the rest (a-z)
	return s.translate(tr).upper()


def normalize_phone(strRaw):
	"""Strip every non-digit char and take the last 10 digits. Return whatever remains."""
	strDigits = re.sub(r"\D", "", strRaw or "")
	return strDigits[-10:]


RETURN_DHL_STATUS_MAP = {
	1: "Order Created",
	2: "In Transit",
	3: "In Transit",
	4: "In Transit",
	5: "Delivered",
	6: "Delivery Failed",
	7: "In Transit",
	8: "Support Needed",
}


def _log_api_request(docDHLSettings, strTitle, strMethod, strURL, dctHeaders, dctPayload=None):
	if docDHLSettings.enable_detailed_logs:
		lstExcludeKeys = ("Authorization", "x-ibm-client-secret")
		dctSafeHeaders = {k: v for k, v in dctHeaders.items() if k not in lstExcludeKeys}
		dctLog = {
			"method": strMethod,
			"url": strURL,
			"headers": dctSafeHeaders,
		}
		if dctPayload is not None:
			dctLog["payload"] = dctPayload
		frappe.log_error(strTitle, frappe.as_json(dctLog))

def _is_jwt_exp_valid(strJWT):
	"""Decode the JWT's exp claim and check if the token is still valid.
	Returns True if valid (or if decoding fails — let the API validate).
	Returns False only when the JWT exp is definitively in the past."""
	blnValid = True
	try:
		lstParts = strJWT.split(".")
		if len(lstParts) >= 2:
			strPadded = lstParts[1] + "=" * (4 - len(lstParts[1]) % 4)
			dctPayload = json.loads(base64.urlsafe_b64decode(strPadded))
			if "exp" in dctPayload:
				dtExpUTC = datetime.fromtimestamp(dctPayload["exp"], tz=timezone.utc)
				# Add 5-minute safety margin — refresh before actual expiry
				dtExpWithMargin = dtExpUTC + timedelta(minutes=5)
				blnValid = datetime.now(tz=timezone.utc) < dtExpWithMargin
	except Exception:
		# If decoding fails, don't block — let the API validate
		pass
	return blnValid

@frappe.whitelist()
def get_token(blnForce=False):
	dctResult = frappe._dict({
		"op_result": False,
		"op_message": "",
		"token": ""
	})

	docDHLSettings = frappe.get_single("DHL Cargo Settings")

	# Return cached token if it is still valid and not forced
	if not blnForce:
		strExistingToken = docDHLSettings.jwt_token or ""
		strExpireDate = docDHLSettings.jwt_expire_date or ""
		if strExistingToken and strExpireDate:
			# FIX #1: Use proper datetime comparison instead of fragile string comparison
			# FIX #2: Also decode JWT exp claim as authoritative source — the jwtExpireDate
			# field from the API may not exactly match the JWT's embedded exp claim
			blnCacheValid = False
			try:
				dtExpire = datetime.strptime(strExpireDate, "%Y-%m-%d %H:%M:%S")
				dtNow = datetime.strptime(frappe.utils.now()[:19], "%Y-%m-%d %H:%M:%S")
				blnCacheValid = dtExpire > dtNow
			except Exception:
				blnCacheValid = False

			# Decode JWT exp claim for additional validation — it is the authoritative
			# expiry that the API gateway actually checks
			if blnCacheValid:
				blnCacheValid = _is_jwt_exp_valid(strExistingToken)

			if blnCacheValid:
				dctResult.op_result = True
				dctResult.op_message = _("Token is valid")
				dctResult.token = strExistingToken
				return dctResult


	strTokenURL = docDHLSettings.web_service_url + "/mngapi/api/token"

	dctPayload = {
		"customerNumber": docDHLSettings.customer_number,
		"password": docDHLSettings.get_password("password"),
		"identityType": 1
	}

	dctHeaders = {
		"x-ibm-client-id": docDHLSettings.client_id,
		"x-ibm-client-secret": docDHLSettings.get_password("client_secret"),
		"Content-Type": "application/json"
	}

	try:
		_log_api_request(docDHLSettings, "DHL Get Token Request", "POST", strTokenURL, dctHeaders, dctPayload)
		response = requests.post(strTokenURL, json=dctPayload, headers=dctHeaders, timeout=30)

		if docDHLSettings.enable_detailed_logs:
			frappe.log_error("DHL Get Token Response", frappe.as_json({
				"status_code": response.status_code,
				"headers": dict(response.headers),
				"body": response.text
			}))

		dctResponse = response.json()
		strJWT = dctResponse.get("jwt")

		if strJWT:
			docDHLSettings.jwt_token = strJWT
			docDHLSettings.refresh_token = dctResponse.get("refreshToken")
			strNewExpireDate = dctResponse.get("jwtExpireDate")
			if strNewExpireDate:
				docDHLSettings.jwt_expire_date = datetime.strptime(
					strNewExpireDate, "%d.%m.%Y %H:%M:%S"
				).strftime("%Y-%m-%d %H:%M:%S")
			docDHLSettings.save(ignore_permissions=True)
			dctResult.op_result = True
			dctResult.op_message = _("Token obtained")
			dctResult.token = strJWT
		else:
			strErrorMessage = ""
			# Handle ERROR_1 format: {"error": {"Code": "...", "Message": "...", "Description": "..."}}
			if "error" in dctResponse and isinstance(dctResponse["error"], dict):
				error_dict = dctResponse["error"]
				# Build a message from the error dict
				parts = []
				if error_dict.get("Code"):
					parts.append(f"Error {error_dict['Code']}")
				if error_dict.get("Message"):
					parts.append(error_dict["Message"])
				if error_dict.get("Description"):
					parts.append(error_dict["Description"])
				strErrorMessage = " - ".join(parts)
			# Handle ERROR_2 format: {"httpCode": "...", "httpMessage": "...", "moreInformation": "..."}
			elif "httpMessage" in dctResponse or "moreInformation" in dctResponse:
				strHTTPMessage = dctResponse.get("httpMessage", "")
				strMoreInfo = dctResponse.get("moreInformation", "")
				strErrorMessage = " ".join(filter(None, [strHTTPMessage, strMoreInfo]))
			# Fallback: if we still don't have a message, use a generic one
			if not strErrorMessage:
				strErrorMessage = "Unknown error"
			dctResult.op_result = False
			dctResult.op_message = strErrorMessage
	except Exception:
		frappe.log_error("DHL Get Token Error", frappe.get_traceback())
		dctResult.op_result = False
		dctResult.op_message = "Failed to obtain token — check Error Log for details"

	return dctResult

@frappe.whitelist()
def get_cities_and_districts():
	dctResult = frappe._dict({
		"op_result": False,
		"op_message": ""
	})

	try:
		frappe.enqueue(
			"dhl_ecommerce_integration.utils._refresh_cities_and_districts_background",
			queue="long",
			timeout=1400,
			job_id="dhl_refresh_cities_and_districts"
		)
		dctResult.op_result = True
		dctResult.op_message = "Refreshing cities and districts in the background. Check Error Log for progress."
	except Exception:
		frappe.log_error("DHL Enqueue Refresh Error", frappe.get_traceback())
		dctResult.op_result = False
		dctResult.op_message = "Failed to start background refresh — check Error Log for details"

	return dctResult


def _refresh_cities_and_districts_background():
	dctResult = frappe._dict({
		"op_result": False,
		"op_message": ""
	})

	docDHLSettings = frappe.get_single("DHL Cargo Settings")
	strBaseURL = docDHLSettings.web_service_url

	dctHeaders = {
		"x-ibm-client-id": docDHLSettings.client_id,
		"x-ibm-client-secret": docDHLSettings.get_password("client_secret"),
		"Content-Type": "application/json"
	}

	try:
		strCitiesURL = strBaseURL + "/mngapi/api/cbsinfoapi/getcities"
		_log_api_request(docDHLSettings, "DHL Get Cities Request", "GET", strCitiesURL, dctHeaders)
		response = requests.get(strCitiesURL, headers=dctHeaders, timeout=30)
		lstCities = response.json()

		if docDHLSettings.enable_detailed_logs:
			frappe.log_error("DHL Get Cities Response", frappe.as_json({
				"status_code": response.status_code,
				"headers": dict(response.headers),
				"body": response.text
			}))

		# Preserve existing examples keyed by city code
		dctExistingCityExamples = {}
		for row in docDHLSettings.cities:
			if row.code:
				dctExistingCityExamples[row.code] = row.examples

		# Preserve existing district examples keyed by "city_code|district_code"
		dctExistingDistrictExamples = {}
		for row in docDHLSettings.districts:
			if row.city_code and row.code:
				strKey = row.city_code + "|" + row.code
				dctExistingDistrictExamples[strKey] = row.examples

		lstNewCities = []
		lstNewDistricts = []
		dTotalCities = len(lstCities)

		for dIndex, dctCity in enumerate(lstCities):
			strCityCode = dctCity.get("code", "")
			strCityName = dctCity.get("name", "")
			if not strCityCode or not strCityName:
				continue

			lstNewCities.append({
				"code": strCityCode,
				"city_name": strCityName,
				"examples": dctExistingCityExamples.get(strCityCode, "")
			})

			frappe.publish_progress(
				percent=int(((dIndex + 1) / dTotalCities) * 100),
				title="Refreshing Cities and Districts",
				description="Fetching districts for " + strCityName + "..."
			)

			strDistrictsURL = strBaseURL + "/mngapi/api/cbsinfoapi/getdistricts/" + strCityCode
			try:
				_log_api_request(docDHLSettings, "DHL Get Districts Request " + strCityCode, "GET", strDistrictsURL, dctHeaders)
				dctDistrictResponse = requests.get(strDistrictsURL, headers=dctHeaders, timeout=30)
				lstDistricts = dctDistrictResponse.json()

				if docDHLSettings.enable_detailed_logs:
					frappe.log_error("DHL Get Districts Response " + strCityCode, frappe.as_json({
						"status_code": dctDistrictResponse.status_code,
						"headers": dict(dctDistrictResponse.headers),
						"body": dctDistrictResponse.text
					}))

				for dctDistrict in lstDistricts:
					strDistrictCode = dctDistrict.get("code", "")
					strDistrictName = dctDistrict.get("name", "")
					if not strDistrictCode or not strDistrictName:
						continue

					strKey = strCityCode + "|" + strDistrictCode
					lstNewDistricts.append({
						"code": strDistrictCode,
						"district_name": strDistrictName,
						"city_code": strCityCode,
						"city_name": strCityName,
						"examples": dctExistingDistrictExamples.get(strKey, "")
					})
			except Exception:
				frappe.log_error("DHL Get Districts Error " + strCityCode, frappe.get_traceback())

		docDHLSettings.set("cities", lstNewCities)
		docDHLSettings.set("districts", lstNewDistricts)
		docDHLSettings.save(ignore_permissions=True)

		dctResult.op_result = True
		dctResult.op_message = "DHL Refresh Cities and Districts completed successfully."
		#frappe.log_error("DHL Refresh Cities and Districts", "Completed successfully")
	except Exception:
		dctResult.op_result = False
		dctResult.op_message = "City and District Refresh Failed! " + frappe.get_traceback()
		frappe.log_error("DHL Refresh Cities and Districts Error", dctResult.op_message)
		
	docDHLSettings.add_comment("Comment", dctResult.op_message)

def create_recipient(doc, method):
	dctResult = frappe._dict({
		"op_result": False,
		"op_message": ""
	})

	if method == "on_submit":
		docDHLSettings = frappe.get_single("DHL Cargo Settings")
		if docDHLSettings.enabled and docDHLSettings.sales_order_creates_recipient:
			docAddress = frappe.get_doc("Address", doc.shipping_address_name)
			docAddress.city = uppercase_tr(docAddress.city)
			docAddress.county = uppercase_tr(docAddress.county)

			strCityCode = None
			for row in docDHLSettings.cities:
				if row.city_name and docAddress.city and row.city_name == docAddress.city:
					strCityCode = row.code
					break

			if not strCityCode:
				dctResult.op_message = "City not mapped in DHL Cargo Settings: {0} for Sales Order {1}!".format(docAddress.city or "", doc.name)
				frappe.log_error("DHL Create Recipient Error", dctResult.op_message)
			else:
				strDistrictCode = None
				for row in docDHLSettings.districts:
					if (row.city_code == strCityCode and row.district_name and docAddress.county and row.district_name == docAddress.county):
						strDistrictCode = row.code
						break

				if not strDistrictCode:
					dctResult.op_message = "District not mapped in DHL Cargo Settings: {0} for Sales Order {1}!".format(docAddress.county or "", doc.name)
					frappe.log_error("DHL Create Recipient Error", dctResult.op_message)
				else:
					# get_token() handles all cache/expiry/refresh logic internally
					dctTokenResult = get_token()
					if not dctTokenResult.op_result:
						dctResult.op_message = "Get Token failed: " + dctTokenResult.op_message
						frappe.log_error("DHL Create Recipient Error", dctResult.op_message)
					else:
						dctResult = _send_create_recipient(doc, docDHLSettings, docAddress, strCityCode, strDistrictCode, dctTokenResult.token)

		doc.add_comment("Comment", dctResult.op_message)
	return dctResult


def _send_create_recipient(doc, docDHLSettings, docAddress, strCityCode, strDistrictCode, strToken):
	dctResult = frappe._dict({
		"op_result": False,
		"op_message": ""
	})

	strCreateURL = docDHLSettings.web_service_url + "/mngapi/api/pluscmdapi/createRecipient"

	strMobile = normalize_phone(docAddress.phone or docDHLSettings.default_phone or "")
	strEmail = docAddress.email_id or docDHLSettings.default_email or ""
	docCustomer = frappe.get_doc("Customer", doc.customer)

	strTaxOffice = (docCustomer.custom_tax_office or "")[:20]
	strTaxNumber = (docCustomer.tax_id or "")[:20]

	dctPayload = {
		"recipient": {
			"customerId": "",
			"refCustomerId": "",
			"cityCode": int(strCityCode),
			"districtCode": int(strDistrictCode),
			"cityName": docAddress.city or "",
			"districtName": docAddress.county or "",
			"address": (docAddress.address_line1 or "") + (docAddress.address_line2 or ""),
			"fullName": doc.customer_name or "",
			"mobilePhoneNumber": strMobile,
			"bussinessPhoneNumber": "",
			"homePhoneNumber": "",
			"email": strEmail,
			"taxOffice": strTaxOffice,
			"taxNumber": strTaxNumber
		}
	}

	dctHeaders = {
		"x-ibm-client-id": docDHLSettings.client_id,
		"x-ibm-client-secret": docDHLSettings.get_password("client_secret"),
		"Content-Type": "application/json",
		"Authorization": "Bearer " + strToken
	}

	try:
		_log_api_request(docDHLSettings, "DHL Create Recipient Request", "POST", strCreateURL, dctHeaders, dctPayload)
		response = requests.post(strCreateURL, json=dctPayload, headers=dctHeaders, timeout=30)

		if docDHLSettings.enable_detailed_logs:
			frappe.log_error("DHL Create Recipient Response", frappe.as_json({
				"status_code": response.status_code,
				"headers": dict(response.headers),
				"body": response.text
			}))

		dctResult.status_code = response.status_code

		if response.status_code == 200:
			dctResult.op_result = True
			dctResult.op_message = "Recipient created successfully"
		else:
			dctResult.op_message = "HTTP {0}: {1}".format(response.status_code, response.text[:500])
			frappe.log_error("DHL Create Recipient Error", dctResult.op_message)
	except Exception:
		dctResult.status_code = 0
		dctResult.op_message = "Exception during createRecipient: " + frappe.get_traceback()
		frappe.log_error("DHL Create Recipient Exception", dctResult.op_message)

	return dctResult


def on_submit_delivery_note(doc, method):
	if doc.custom_ld_delivery_method == "DHL":
		if frappe.db.get_single_value("DHL Cargo Settings", "enabled"):
			if not doc.dhl_barcodes or len(doc.dhl_barcodes) == 0:
				frappe.throw(_("DHL Barcode rows (desi/kg) must be filled before submitting a DHL Delivery Note."))
			else:
				_create_order_on_submit(doc)


def _create_order_on_submit(doc):
	dctResult = frappe._dict({
		"op_result": False,
		"op_message": ""
	})

	docDHLSettings = frappe.get_single("DHL Cargo Settings")
	if not docDHLSettings.enabled:
		frappe.throw("DHL Cargo Settings is not enabled!")
	elif not doc.shipping_address_name:
		frappe.throw("Shipping address is required for DHL cargo")
	else:
		lstParcels = []
		for docRow in doc.dhl_barcodes:
			lstParcels.append({
				"desi": docRow.desi or 1,
				"kg": docRow.kg or 1,
			})

		dctTokenResult = get_token()
		if not dctTokenResult.op_result:
			frappe.throw("Get Token failed: " + dctTokenResult.op_message)
		else:
			dctPayload = _build_create_order_payload(doc, lstParcels)
			dctHeaders = {
				"x-ibm-client-id": docDHLSettings.client_id,
				"x-ibm-client-secret": docDHLSettings.get_password("client_secret"),
				"Content-Type": "application/json",
				"Authorization": "Bearer " + dctTokenResult.token
			}
			strURL = docDHLSettings.web_service_url + "/mngapi/api/standardcmdapi/createOrder"
			dctResult = _send_create_order(dctPayload, dctHeaders, strURL, docDHLSettings)

			if dctResult.op_result:
				frappe.db.set_value("Delivery Note", doc.name, {
					"dhl_reference_id": dctResult.reference_id or "",
					"dhl_order_invoice_id": dctResult.order_invoice_id or "",
					"dhl_shipper_branch_code": dctResult.shipper_branch_code or "",
				})
				doc.add_comment("Comment", "DHL CreateOrder succeeded. OrderInvoiceId: {0}, ShipperBranchCode: {1}, ReferenceId: {2}".format(
					dctResult.order_invoice_id or "", dctResult.shipper_branch_code or "", dctResult.reference_id or ""
				))
			else:
				doc.add_comment("Comment", "DHL CreateOrder failed: " + dctResult.op_message)
				frappe.throw("DHL CreateOrder failed: " + dctResult.op_message)

	return dctResult


@frappe.whitelist()
def create_barcode(strDeliveryNoteName, lstParcels):
	dctResult = frappe._dict({
		"op_result": False,
		"op_message": ""
	})

	if isinstance(lstParcels, str):
		lstParcels = json.loads(lstParcels)

	docDHLSettings = frappe.get_single("DHL Cargo Settings")
	if not docDHLSettings.enabled:
		frappe.throw("DHL Cargo Settings is not enabled!")
	else:
		docDN = frappe.get_doc("Delivery Note", strDeliveryNoteName)
		if docDN.custom_ld_delivery_method == "DHL":
			if not docDN.dhl_reference_id:
				frappe.throw("CreateOrder must be completed before barcode generation for {0}".format(docDN.name))
			else:
				dctTokenResult = get_token()
				if not dctTokenResult.op_result:
					frappe.throw("Get Token failed: " + dctTokenResult.op_message)
				else:
					strReferenceId = docDN.dhl_reference_id
					lstItemGroups = list(dict.fromkeys([item.item_group for item in docDN.items if item.item_group]))
					strFirstItemGroup = lstItemGroups[0] if lstItemGroups else ""

					dctHeaders = {
						"x-ibm-client-id": docDHLSettings.client_id,
						"x-ibm-client-secret": docDHLSettings.get_password("client_secret"),
						"Content-Type": "application/json",
						"Authorization": "Bearer " + dctTokenResult.token
					}
					dctBCPayload = _build_create_barcode_payload(strReferenceId, lstParcels, strFirstItemGroup)
					strBCURL = docDHLSettings.web_service_url + "/mngapi/api/barcodecmdapi/createbarcode"
					dctBCResult = _send_create_barcode(dctBCPayload, dctHeaders, strBCURL, docDHLSettings)

					if dctBCResult.op_result:
						dctResult.barcodes = dctBCResult.barcodes
						dctResult.invoice_id = dctBCResult.invoice_id
						dctResult.shipment_id = dctBCResult.shipment_id
						dctResult.op_result = True
						dctResult.op_message = "CreateBarcode succeeded"
						frappe.db.set_value("Delivery Note", strDeliveryNoteName, {
							"dhl_barcode_invoice_id": dctBCResult.invoice_id or "",
							"dhl_shipment_id": dctBCResult.shipment_id or "",
						})
						dctSyncResult = _sync_barcode_rows(docDN.dhl_barcodes, dctBCResult.barcodes, lstParcels, strDeliveryNoteName)
						docDN.add_comment("Comment", "DHL CreateBarcode succeeded. InvoiceId: {0}, ShipmentId: {1}, Pieces: {2}".format(
							dctBCResult.invoice_id or "", dctBCResult.shipment_id or "", dctSyncResult.synced_count
						))
						dctPDFResult = _generate_pdfs_for_dn(strDeliveryNoteName)
						if dctPDFResult.op_result:
							dctResult.pdf_urls = dctPDFResult.lst_file_urls
							docDN.add_comment("Comment", "DHL PDF labels generated: {0} files".format(len(dctPDFResult.lst_file_urls)))
						else:
							docDN.add_comment("Comment", "DHL PDF generation failed: " + dctPDFResult.op_message)
					else:
						dctResult.op_result = False
						dctResult.op_message = "CreateBarcode failed: " + dctBCResult.op_message
						docDN.add_comment("Comment", "DHL CreateBarcode failed: " + dctBCResult.op_message)

	return dctResult


def _sync_barcode_rows(lstRows, lstBarcodes, lstParcels, strDocName):
	dctResult = frappe._dict({"op_result": False, "op_message": "", "synced_count": 0})
	dTotalPieces = len(lstParcels)
	dSyncedCount = 0

	for dctEntry in (lstBarcodes or []):
		dPiece = int(dctEntry.get("pieceNumber", 0))
		dIdx = dPiece - 1
		dctParcel = lstParcels[dIdx] if dIdx < len(lstParcels) else {}
		strPieceBarcode = _make_piece_barcode(strDocName, dPiece, dTotalPieces)
		dctRowData = {
			"barcode": strPieceBarcode,
			"barcode_zpl": dctEntry.get("value", ""),
			"piece_number": dPiece,
			"desi": dctParcel.get("desi", 0),
			"kg": dctParcel.get("kg", 0),
		}
		if dIdx < len(lstRows):
			frappe.db.set_value("DHL Barcode", lstRows[dIdx].name, dctRowData)
			lstRows[dIdx].update(dctRowData)
		else:
			docNewRow = frappe.new_doc("DHL Barcode")
			docNewRow.parent = strDocName
			docNewRow.parenttype = "Delivery Note"
			docNewRow.parentfield = "dhl_barcodes"
			docNewRow.update(dctRowData)
			docNewRow.db_insert()
			lstRows.append(docNewRow)
		dSyncedCount += 1

	while len(lstRows) > len(lstBarcodes or []):
		objExcess = lstRows.pop()
		if hasattr(objExcess, "name") and objExcess.name:
			frappe.db.delete("DHL Barcode", {"name": objExcess.name})
		frappe.log_error("DHL Barcode Sync Warning", "Removed excess barcode row from {0}".format(strDocName))

	dctResult.synced_count = dSyncedCount
	if dSyncedCount == len(lstBarcodes or []):
		dctResult.op_result = True
		dctResult.op_message = "Barcode rows synced successfully"
	else:
		dctResult.op_message = "Expected {0} barcodes, synced {1}".format(len(lstBarcodes or []), dSyncedCount)

	return dctResult


def _make_piece_barcode(strReferenceId, dPieceNumber, dTotalPieces):
	if dTotalPieces <= 1:
		return strReferenceId
	strSuffix = "-{0:02d}".format(dPieceNumber)
	if len(strReferenceId) + len(strSuffix) > 30:
		strSuffix = "-{0}".format(dPieceNumber)
	if len(strReferenceId) + len(strSuffix) > 30:
		strReferenceId = strReferenceId[:30 - len(strSuffix)]
	return strReferenceId + strSuffix


def _build_create_order_payload(docDN, lstParcels):
	docDHLSettings = frappe.get_single("DHL Cargo Settings")
	docAddress = frappe.get_doc("Address", docDN.shipping_address_name)
	docAddress.city = uppercase_tr(docAddress.city)
	docAddress.county = uppercase_tr(docAddress.county)

	strCityCode = "0"
	for row in docDHLSettings.cities:
		if row.city_name and row.city_name == docAddress.city:
			strCityCode = row.code
			break

	strDistrictCode = "0"
	for row in docDHLSettings.districts:
		if row.city_code == strCityCode and row.district_name and row.district_name == docAddress.county:
			strDistrictCode = row.code
			break

	lstItemGroups = list(dict.fromkeys([item.item_group for item in docDN.items if item.item_group]))
	strContent = " ".join(lstItemGroups)[:200]
	strFirstItemGroup = docDN.items[0].item_group if docDN.items else ""
	strReferenceId = docDN.name

	strMobile = normalize_phone(docAddress.phone or docDHLSettings.default_phone or "")
	strEmail = docAddress.email_id or docDHLSettings.default_email or ""
	strAddress = (docAddress.address_line1 or "") + " " + (docAddress.address_line2 or "")

	lstOrderPieces = []
	for i, dctParcel in enumerate(lstParcels, start=1):
		lstOrderPieces.append({
			"barcode": _make_piece_barcode(strReferenceId, i, len(lstParcels)),
			"desi": dctParcel.get("desi", 1),
			"kg": dctParcel.get("kg", 1),
			"content": strFirstItemGroup
		})

	dctPayload = {
		"order": {
			"referenceId": strReferenceId,
			"barcode": strReferenceId,
			"billOfLandingId": "",
			"isCOD": 0,
			"codAmount": 0,
			"shipmentServiceType": 1,
			"packagingType": 3,
			"content": strContent,
			"smsPreference1": 0,
			"smsPreference2": 0,
			"smsPreference3": 0,
			"paymentType": 1,
			"deliveryType": 1,
			"description": "Paket Hazırlandı",
			"marketPlaceShortCode": "",
			"marketPlaceSaleCode": "",
			"pudoId": ""
		},
		"orderPieceList": lstOrderPieces,
		"recipient": {
			"customerId": "",
			"refCustomerId": "",
			"cityCode": int(strCityCode),
			"districtCode": int(strDistrictCode),
			"cityName": docAddress.city or "",
			"districtName": docAddress.county or "",
			"address": strAddress.strip(),
			"fullName": docAddress.address_title or "",
			"mobilePhoneNumber": strMobile,
			"bussinessPhoneNumber": "",
			"homePhoneNumber": "",
			"email": strEmail,
			"taxOffice": "",
			"taxNumber": ""
		}
	}

	return dctPayload


def _build_create_barcode_payload(strReferenceId, lstParcels, strFirstItemGroup):
	dTotalPieces = len(lstParcels)
	dctPayload = {
		"referenceId": strReferenceId,
		"billOfLandingId": "",
		"isCOD": 0,
		"codAmount": 0,
		"printReferenceBarcodeOnError": 0,
		"message": "",
		"additionalContent1": "",
		"additionalContent2": "",
		"additionalContent3": "",
		"additionalContent4": "",
		"packagingType": 3,
		"orderPieceList": [
			{
				"barcode": _make_piece_barcode(strReferenceId, i, dTotalPieces),
				"desi": dctParcel.get("desi", 1),
				"kg": dctParcel.get("kg", 1),
				"content": strFirstItemGroup
			} for i, dctParcel in enumerate(lstParcels, start=1)
		]
	}
	return dctPayload


def _send_create_order(dctPayload, dctHeaders, strURL, docDHLSettings):
	dctResult = frappe._dict({
		"op_result": False,
		"op_message": ""
	})

	try:
		_log_api_request(docDHLSettings, "DHL CreateOrder Request", "POST", strURL, dctHeaders, dctPayload)
		objResponse = requests.post(strURL, json=dctPayload, headers=dctHeaders, timeout=30)

		if docDHLSettings.enable_detailed_logs:
			frappe.log_error("DHL CreateOrder Response", frappe.as_json({
				"status_code": objResponse.status_code,
				"headers": dict(objResponse.headers),
				"body": objResponse.text
			}))

		dctResult.status_code = objResponse.status_code

		if objResponse.status_code == 200:
			lstData = objResponse.json()
			if isinstance(lstData, list) and len(lstData) > 0:
				dctFirst = lstData[0]
				dctResult.op_result = True
				dctResult.op_message = "CreateOrder succeeded"
				dctResult.reference_id = dctFirst.get("referenceId")
				dctResult.order_invoice_id = dctFirst.get("orderInvoiceId")
				dctResult.order_invoice_detail_id = dctFirst.get("orderInvoiceDetailId")
				dctResult.shipper_branch_code = dctFirst.get("shipperBranchCode")
			else:
				dctResult.op_message = "Unexpected response format: " + str(lstData)[:500]
				frappe.log_error("DHL CreateOrder Error", dctResult.op_message)
		else:
			dctResult.op_message = "HTTP {0}: {1}".format(objResponse.status_code, objResponse.text[:500])
			frappe.log_error("DHL CreateOrder Error", dctResult.op_message)
	except Exception:
		dctResult.status_code = 0
		dctResult.op_message = "Exception during createOrder: " + frappe.get_traceback()
		frappe.log_error("DHL CreateOrder Exception", dctResult.op_message)

	return dctResult


def _flatten_barcode_elements(lstData):
	dctResult = frappe._dict({"op_result": False, "op_message": "", "invoice_id": None, "shipment_id": None, "barcodes": []})

	if not isinstance(lstData, list) or len(lstData) == 0:
		dctResult.op_message = "Unexpected response format: " + str(lstData)[:500]
		return dctResult

	strBaseRef = None
	lstFlatBarcodes = []

	for dctElement in lstData:
		if strBaseRef is None:
			strBaseRef = dctElement.get("referenceId")
			dctResult.invoice_id = dctElement.get("invoiceId")
			dctResult.shipment_id = dctElement.get("shipmentId")
		elif dctElement.get("referenceId") and dctElement.get("referenceId") != strBaseRef:
			frappe.log_error("DHL CreateBarcode Warning", "Non-uniform referenceId in response element: {0} vs base {1}".format(
				dctElement.get("referenceId"), strBaseRef
			))

		lstPieceBarcodes = dctElement.get("barcodes", [])
		for dctBarcode in lstPieceBarcodes:
			lstFlatBarcodes.append(dctBarcode)

	if len(lstFlatBarcodes) == 0:
		dctResult.op_message = "CreateBarcode returned no piece barcodes"
		frappe.log_error("DHL CreateBarcode Error", dctResult.op_message)
	else:
		dctResult.op_result = True
		dctResult.op_message = "CreateBarcode succeeded"
		dctResult.barcodes = lstFlatBarcodes

	return dctResult


def _send_create_barcode(dctPayload, dctHeaders, strURL, docDHLSettings):
	dctResult = frappe._dict({"op_result": False, "op_message": ""})

	try:
		_log_api_request(docDHLSettings, "DHL CreateBarcode Request", "POST", strURL, dctHeaders, dctPayload)
		objResponse = requests.post(strURL, json=dctPayload, headers=dctHeaders, timeout=30)

		if docDHLSettings.enable_detailed_logs:
			frappe.log_error("DHL CreateBarcode Response", frappe.as_json({
				"status_code": objResponse.status_code,
				"headers": dict(objResponse.headers),
				"body": objResponse.text
			}))

		dctResult.status_code = objResponse.status_code

		if objResponse.status_code == 200:
			lstData = objResponse.json()
			dctResult = _flatten_barcode_elements(lstData)
			dctResult.status_code = 200
		else:
			dctResult.op_message = "HTTP {0}: {1}".format(objResponse.status_code, objResponse.text[:500])
			frappe.log_error("DHL CreateBarcode Error", dctResult.op_message)
	except Exception:
		dctResult.status_code = 0
		dctResult.op_message = "Exception during createBarcode: " + frappe.get_traceback()
		frappe.log_error("DHL CreateBarcode Exception", dctResult.op_message)

	return dctResult


def _convert_zpl_to_pdf(lstZpl):
	strLabelaryURL = "https://api.labelary.com/v1/printers/8dpmm/labels/4x4/0/"
	dctHeaders = {"accept": "application/pdf", "content-type": "application/x-www-form-urlencoded"}
	strCombinedZpl = "\n".join(lstZpl)
	bytPdf = None
	try:
		objResponse = requests.post(strLabelaryURL, data=strCombinedZpl, headers=dctHeaders, timeout=30)
		if objResponse.status_code == 200:
			bytPdf = objResponse.content
		elif objResponse.status_code == 429:
			dRetryAfter = int(objResponse.headers.get("Retry-After", 1))
			time.sleep(dRetryAfter)
			objResponse = requests.post(strLabelaryURL, data=strCombinedZpl, headers=dctHeaders, timeout=30)
			if objResponse.status_code == 200:
				bytPdf = objResponse.content
			else:
				frappe.log_error("DHL Labelary Error", "HTTP {0}: {1}".format(objResponse.status_code, objResponse.text[:500]))
		else:
			frappe.log_error("DHL Labelary Error", "HTTP {0}: {1}".format(objResponse.status_code, objResponse.text[:500]))
	except Exception:
		frappe.log_error("DHL Labelary Exception", frappe.get_traceback())
	return bytPdf


def _attach_pdf_to_dn(strDNName, bytPdf, strFileName):
	strFileURL = None
	try:
		docFile = frappe.get_doc({
			"doctype": "File",
			"file_name": strFileName,
			"content": bytPdf,
			"is_private": 1,
			"attached_to_doctype": "Delivery Note",
			"attached_to_name": strDNName,
		})
		docFile.insert(ignore_permissions=True)
		strFileURL = docFile.file_url
	except Exception:
		frappe.log_error("DHL Attach PDF Exception", frappe.get_traceback())
	return strFileURL


def _delete_stale_label_files(strDNName):
	dctResult = frappe._dict({"op_result": True, "op_message": "", "intDeleted": 0})
	strFileNamePattern = "DHL_Etiketi_{0}_%".format(strDNName)
	try:
		lstFileNames = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "Delivery Note",
				"attached_to_name": strDNName,
				"file_name": ("like", strFileNamePattern),
			},
			pluck="name",
		)
	except Exception:
		dctResult.op_result = False
		dctResult.op_message = "Failed to query stale label files"
		frappe.log_error("DHL Label Cleanup Query Error", frappe.get_traceback())
		return dctResult

	for strFileName in lstFileNames:
		try:
			frappe.delete_doc("File", strFileName, ignore_permissions=True)
			dctResult.intDeleted += 1
		except Exception:
			dctResult.op_message += "Failed to delete {0}; ".format(strFileName)
			frappe.log_error("DHL Label Cleanup Delete Error", "File: {0}\n{1}".format(strFileName, frappe.get_traceback()))

	return dctResult


def _generate_pdfs_for_dn(strDNName):
	dctResult = frappe._dict({"op_result": True, "op_message": "", "lst_file_urls": [], "int_deleted": 0})
	docDN = frappe.get_doc("Delivery Note", strDNName)
	if not docDN.dhl_barcodes:
		dctResult.op_result = False
		dctResult.op_message = "No DHL barcodes found"
	else:
		lstConverted = []
		for docBCRow in docDN.dhl_barcodes:
			if not docBCRow.barcode_zpl:
				continue
			bytPdf = _convert_zpl_to_pdf([docBCRow.barcode_zpl])
			if bytPdf is None:
				dctResult.op_result = False
				dctResult.op_message = "PDF conversion failed for piece {0}".format(docBCRow.piece_number)
				return dctResult
			lstConverted.append((docBCRow.piece_number, bytPdf))

		if not lstConverted:
			dctResult.op_result = False
			dctResult.op_message = "PDF generation failed"
			return dctResult

		dctDeleteResult = _delete_stale_label_files(strDNName)
		dctResult.int_deleted = dctDeleteResult.intDeleted

		for dPieceNumber, bytPdf in lstConverted:
			strFileName = "DHL_Etiketi_{0}_Parca{1}.pdf".format(strDNName, dPieceNumber)
			strFileURL = _attach_pdf_to_dn(strDNName, bytPdf, strFileName)
			if strFileURL:
				dctResult.lst_file_urls.append(strFileURL)

		if not dctResult.lst_file_urls:
			dctResult.op_result = False
			dctResult.op_message = "PDF generation failed"

	return dctResult


@frappe.whitelist()
def generate_dhl_pdfs(strDeliveryNoteName):
	docDN = frappe.get_doc("Delivery Note", strDeliveryNoteName)
	if not (docDN.custom_ld_delivery_method == "DHL" and docDN.dhl_barcodes):
		frappe.throw("No DHL barcodes found for this Delivery Note")
	dctResult = _generate_pdfs_for_dn(strDeliveryNoteName)
	return dctResult


@frappe.whitelist()
def cancel_dhl_order(strReferenceId):
	"""Cancels a DHL shipment by reference ID via the cancelshipment API."""
	dctResult = frappe._dict({"op_result": False, "op_message": ""})

	if not strReferenceId or not strReferenceId.strip():
		dctResult.op_message = "Reference ID is required"
	else:
		strReferenceId = strReferenceId.strip().upper()
		docDHLSettings = frappe.get_single("DHL Cargo Settings")
		if not docDHLSettings.enabled:
			dctResult.op_message = "DHL Cargo Settings is not enabled"
		else:
			dctTokenResult = get_token()
			if not dctTokenResult.op_result:
				dctResult.op_message = "Get Token failed: " + dctTokenResult.op_message
			else:
				strShipmentId = frappe.db.get_value("Delivery Note", strReferenceId, "dhl_shipment_id") or ""
				dctPayload = {"referenceId": strReferenceId, "shipmentId": strShipmentId}
				dctHeaders = {
					"x-ibm-client-id": docDHLSettings.client_id,
					"x-ibm-client-secret": docDHLSettings.get_password("client_secret"),
					"Content-Type": "application/json",
					"Authorization": "Bearer " + dctTokenResult.token
				}
				strURL = docDHLSettings.web_service_url + "/mngapi/api/barcodecmdapi/cancelshipment"

				try:
					_log_api_request(docDHLSettings, "DHL Cancel Shipment Request", "PUT", strURL, dctHeaders, dctPayload)
					objResponse = requests.put(strURL, json=dctPayload, headers=dctHeaders, timeout=30)

					if docDHLSettings.enable_detailed_logs:
						frappe.log_error("DHL Cancel Shipment Response", frappe.as_json({
							"status_code": objResponse.status_code,
							"headers": dict(objResponse.headers),
							"body": objResponse.text
						}))

					if objResponse.status_code == 200:
						dctResult.op_result = True
						dctResult.op_message = "Shipment {0} cancelled successfully".format(strReferenceId)
					else:
						dctResult.op_message = "HTTP {0}: {1}".format(objResponse.status_code, objResponse.text[:500])
						frappe.log_error("DHL Cancel Shipment Error", dctResult.op_message)
				except Exception:
					dctResult.op_message = "Exception during cancelShipment: " + frappe.get_traceback()
					frappe.log_error("DHL Cancel Shipment Exception", dctResult.op_message)

				docDN = frappe.get_doc("Delivery Note", strReferenceId)
				strStatus = "Başarılı" if dctResult.op_result else "Başarısız"
				docDN.add_comment("Comment", "DHL Kargo İptal — {0}: {1}".format(strStatus, dctResult.op_message))

	return dctResult


def _build_create_return_order_payload(strReferenceId, docSO, docAddress, strItemCode, dReturnQty, docDHLSettings):
	docAddress.city = uppercase_tr(docAddress.city)
	docAddress.county = uppercase_tr(docAddress.county)

	strCityCode = "0"
	for row in docDHLSettings.cities:
		if row.city_name and row.city_name == docAddress.city:
			strCityCode = row.code
			break

	strDistrictCode = "0"
	for row in docDHLSettings.districts:
		if row.city_code == strCityCode and row.district_name and row.district_name == docAddress.county:
			strDistrictCode = row.code
			break

	strItemName = strItemCode
	for docItem in docSO.items:
		if docItem.item_code == strItemCode:
			strItemName = docItem.item_name or strItemCode
			break

	strMobile = normalize_phone(docAddress.phone or docDHLSettings.default_phone or "")
	strEmail = docAddress.email_id or docDHLSettings.default_email or ""

	dctPayload = {
		"order": {
			"referenceId": strReferenceId,
			"barcode": strReferenceId,
			"billOfLandingId": "",
			"isCOD": 0,
			"codAmount": 0,
			"shipmentServiceType": 1,
			"packagingType": 3,
			"content": strItemName[:200],
			"smsPreference1": 0,
			"smsPreference2": 0,
			"smsPreference3": 0,
			"paymentType": 1,
			"deliveryType": 1,
			"description": "ERPNext Return Order",
			"marketPlaceShortCode": "",
			"marketPlaceSaleCode": "",
		},
		"orderPieceList": [
			{
				"barcode": strReferenceId,
				"desi": 1,
				"kg": 1,
				"content": strItemName[:150],
			}
		],
		"shipper": {
			"customerId": "",
			"refCustomerId": "",
			"cityCode": int(strCityCode),
			"districtCode": int(strDistrictCode),
			"cityName": docAddress.city or "",
			"districtName": docAddress.county or "",
			"address": _format_address_helper(docAddress),
			"fullName": docSO.customer_name or "",
			"mobilePhoneNumber": strMobile,
			"bussinessPhoneNumber": "",
			"homePhoneNumber": "",
			"email": strEmail,
			"taxOffice": "",
			"taxNumber": "",
		},
	}

	return dctPayload


def _format_address_helper(docAddress):
	lstParts = []
	if docAddress.address_line1:
		lstParts.append(docAddress.address_line1)
	if docAddress.address_line2:
		lstParts.append(docAddress.address_line2)
	return " ".join(lstParts).strip()


def _send_create_return_order(dctPayload, dctHeaders, strURL, docDHLSettings):
	dctResult = frappe._dict({
		"op_result": False,
		"op_message": "",
		"reference_id": "",
		"order_invoice_id": "",
		"return_label_url": "",
	})

	try:
		_log_api_request(docDHLSettings, "DHL Create Return Order Request", "POST", strURL, dctHeaders, dctPayload)
		objResponse = requests.post(strURL, json=dctPayload, headers=dctHeaders, timeout=30)

		if docDHLSettings.enable_detailed_logs:
			frappe.log_error("DHL Create Return Order Response", frappe.as_json({
				"status_code": objResponse.status_code,
				"headers": dict(objResponse.headers),
				"body": objResponse.text,
			}))

		dctResult.status_code = objResponse.status_code

		if objResponse.status_code == 200:
			lstData = objResponse.json()
			if isinstance(lstData, list) and len(lstData) > 0:
				dctFirst = lstData[0]
				dctResult.op_result = True
				dctResult.op_message = "CreateReturnOrder succeeded"
				dctResult.reference_id = dctFirst.get("referenceId", "")
				dctResult.order_invoice_id = str(dctFirst.get("orderInvoiceId", ""))
				dctResult.return_label_url = dctFirst.get("returnOrderLabelURL", "")
			else:
				dctResult.op_message = "Unexpected response format: " + str(lstData)[:500]
				frappe.log_error("DHL Create Return Order Error", dctResult.op_message)
		else:
			dctResult.op_message = "HTTP {0}: {1}".format(objResponse.status_code, objResponse.text[:500])
			frappe.log_error("DHL Create Return Order Error", dctResult.op_message)
	except Exception:
		dctResult.status_code = 0
		dctResult.op_message = "Exception during createReturnOrder: " + frappe.get_traceback()
		frappe.log_error("DHL Create Return Order Exception", dctResult.op_message)

	return dctResult


@frappe.whitelist()
def check_return_status(strDHLReturnOrderName):
	dctResult = frappe._dict({
		"op_result": False,
		"op_message": "",
	})

	if not frappe.has_permission("DHL Return Order", "write"):
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)

	docReturn = frappe.get_doc("DHL Return Order", strDHLReturnOrderName)
	if not docReturn.reference_id:
		dctResult.op_message = "No reference ID found"
	else:
		docDHLSettings = frappe.get_single("DHL Cargo Settings")
		if not docDHLSettings.enabled:
			dctResult.op_message = "DHL Cargo Settings is not enabled"
		else:
			dctTokenResult = get_token()
			if not dctTokenResult.op_result:
				dctResult.op_message = "Get Token failed: " + dctTokenResult.op_message
			else:
				strBaseURL = docDHLSettings.web_service_url
				strReferenceId = docReturn.reference_id
				dctHeaders = {
					"x-ibm-client-id": docDHLSettings.client_id,
					"x-ibm-client-secret": docDHLSettings.get_password("client_secret"),
					"Content-Type": "application/json",
					"Authorization": "Bearer " + dctTokenResult.token,
				}
				strNewStatus = ""
				strInfoMessage = ""

				strStatusURL = strBaseURL + "/mngapi/api/standardqueryapi/getshipmentstatus/" + quote(strReferenceId, safe="")
				try:
					_log_api_request(docDHLSettings, "DHL Manual Return Status Check", "GET", strStatusURL, dctHeaders)
					objResponse = requests.get(strStatusURL, headers=dctHeaders, timeout=30)

					if objResponse.status_code == 200:
						dctData = objResponse.json()
						if isinstance(dctData, list) and len(dctData) > 0:
							dctData = dctData[0]
						dStatusCode = dctData.get("shipmentStatusCode") if isinstance(dctData, dict) else None
						strInfoMessage = dctData.get("shipmentStatus", "") if isinstance(dctData, dict) else ""
						strNewStatus = RETURN_DHL_STATUS_MAP.get(dStatusCode, "")
					elif objResponse.status_code == 401:
						dctRefreshResult = get_token(blnForce=True)
						if dctRefreshResult.op_result:
							dctHeaders["Authorization"] = "Bearer " + dctRefreshResult.token
							objResponse2 = requests.get(strStatusURL, headers=dctHeaders, timeout=30)
							if objResponse2.status_code == 200:
								dctData = objResponse2.json()
								if isinstance(dctData, list) and len(dctData) > 0:
									dctData = dctData[0]
								dStatusCode = dctData.get("shipmentStatusCode") if isinstance(dctData, dict) else None
								strInfoMessage = dctData.get("shipmentStatus", "") if isinstance(dctData, dict) else ""
								strNewStatus = RETURN_DHL_STATUS_MAP.get(dStatusCode, "")
						else:
							dctResult.op_message = "Token refresh failed: " + dctRefreshResult.op_message
					elif objResponse.status_code == 404:
						strNewStatus, strInfoMessage = _check_return_order_fallback(
							strReferenceId, strBaseURL, dctHeaders, docDHLSettings
						)
						if strNewStatus is None:
							dctResult.op_message = strInfoMessage
					else:
						dctResult.op_message = "HTTP {0}: {1}".format(objResponse.status_code, objResponse.text[:500])
						frappe.log_error("DHL Manual Return Status Error", dctResult.op_message)
				except Exception:
					dctResult.op_message = "Exception during return status check: " + frappe.get_traceback()
					frappe.log_error("DHL Manual Return Status Exception", dctResult.op_message)

				if strNewStatus:
					try:
						docReturn.status = strNewStatus
						docReturn.dhl_last_tracked = frappe.utils.now_datetime()
						docReturn.save()
						dctResult.op_result = True
						dctResult.op_message = strInfoMessage or strNewStatus
					except Exception:
						dctResult.op_message = "Failed to save return status: " + frappe.get_traceback()
						frappe.log_error("DHL Manual Return Status Save Error", dctResult.op_message)

	return dctResult


def _check_return_order_fallback(strReferenceId, strBaseURL, dctHeaders, docDHLSettings):
	"""Fallback to checkReturnOrder endpoint when getshipmentstatus returns 404.
	Returns (status_string, info_message) on carrier success, (None, error_message) on error."""
	strNewStatus = None
	strInfoMessage = ""
	strPayload = {
		"referenceId": strReferenceId,
		"shipmentId": None,
		"invoiceSerialNumber": None,
		"invoiceNumber": None,
		"barcode": None,
		"shipmentReleaseDate": None,
	}
	strURL = strBaseURL + "/mngapi/api/plusqueryapi/checkReturnOrder"
	try:
		_log_api_request(docDHLSettings, "DHL Check Return Order Fallback", "POST", strURL, dctHeaders, strPayload)
		objResponse = requests.post(strURL, json=strPayload, headers=dctHeaders, timeout=30)
		if objResponse.status_code == 200:
			lstData = objResponse.json()
			if isinstance(lstData, list) and len(lstData) > 0:
				strNewStatus = "Order Created"
				strInfoMessage = lstData[0].get("eventStatus", "") if isinstance(lstData[0], dict) else ""
			else:
				strNewStatus = "Not Found"
		else:
			strInfoMessage = "checkReturnOrder fallback HTTP {0}".format(objResponse.status_code)
			frappe.log_error("DHL Check Return Order Fallback Error", strInfoMessage)
	except Exception:
		strInfoMessage = "checkReturnOrder fallback failed: " + frappe.get_traceback()
		frappe.log_error("DHL Check Return Order Fallback Error", strInfoMessage)
	return strNewStatus, strInfoMessage


def validate_address(doc, method):
	#Validates given City and County (District) against DHL Settings city - district pairs
	#Only if DHL Settings enabled and address is for Turkey.
	dctResult = frappe._dict({
		"op_result": True,
		"op_message": ""
	})

	docDHLSettings = frappe.get_single("DHL Cargo Settings")
	if docDHLSettings.enabled:
		strCountryCode = frappe.db.get_value("Country", doc.country, "code") if doc.country else ""

		#Check if country is actually Türkiye
		if strCountryCode.upper() == "TR":
			strCity = uppercase_tr(doc.city or "")
			strCounty = uppercase_tr(doc.county or "")

			blnCityValid = False
			strCityCode = ""
			for row in docDHLSettings.cities:
				if row.city_name and row.city_name == strCity:
					blnCityValid = True
					strCityCode = row.code
					break

			if not blnCityValid:
				dctResult.op_result = False
				dctResult.op_message = _("City not mapped in DHL Cargo Settings: {0}!").format(strCity)
			else:
				blnCountyValid = False
				for row in docDHLSettings.districts:
					if row.city_code == strCityCode and row.district_name and row.district_name == strCounty:
						blnCountyValid = True
						break

				if not blnCountyValid:
					dctResult.op_result = False
					dctResult.op_message = _("County not mapped in DHL Cargo Settings: {0}!").format(strCounty)

	if not dctResult.op_result:
		frappe.throw(dctResult.op_message)

	return dctResult