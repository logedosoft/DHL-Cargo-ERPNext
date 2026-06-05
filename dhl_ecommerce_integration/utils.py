# Copyright (c) 2026, Logedosoft Business Solutions and contributors
# For license information, please see license.txt

import frappe, json, requests
from datetime import datetime
from frappe import msgprint, _
from frappe.utils import get_datetime_str

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
		if strExistingToken and strExpireDate and strExpireDate > frappe.utils.now():
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
		response = requests.post(strTokenURL, json=dctPayload, headers=dctHeaders, timeout=30)

		if docDHLSettings.enable_detailed_logs:
			frappe.log_error("DHL Get Token Response", frappe.as_json(response.json()))

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
	docDHLSettings = frappe.get_single("DHL Cargo Settings")
	strBaseURL = docDHLSettings.web_service_url

	dctHeaders = {
		"x-ibm-client-id": docDHLSettings.client_id,
		"x-ibm-client-secret": docDHLSettings.get_password("client_secret"),
		"Content-Type": "application/json"
	}

	try:
		strCitiesURL = strBaseURL + "/mngapi/api/cbsinfoapi/getcities"
		response = requests.get(strCitiesURL, headers=dctHeaders, timeout=30)
		lstCities = response.json()

		if docDHLSettings.enable_detailed_logs:
			frappe.log_error("DHL Get Cities Response", frappe.as_json(lstCities))

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
				dctDistrictResponse = requests.get(strDistrictsURL, headers=dctHeaders, timeout=30)
				lstDistricts = dctDistrictResponse.json()

				if docDHLSettings.enable_detailed_logs:
					frappe.log_error("DHL Get Districts Response " + strCityCode, frappe.as_json(lstDistricts))

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

		frappe.log_error("DHL Refresh Cities and Districts", "Completed successfully")
	except Exception:
		frappe.log_error("DHL Refresh Cities and Districts Error", frappe.get_traceback())


def create_recipient(doc, method):
	# Create the recipient if DHL is active in DHL Cargo Settings
	# Check if we already have a "dhl_customer_id" for the customer.
	if method != "on_submit":
		return

	docDHLSettings = frappe.get_single("DHL Cargo Settings")
	if not docDHLSettings.enabled:
		return

	strDHLCustomerID = frappe.db.get_value("Customer", doc.customer, "dhl_customer_id")
	if strDHLCustomerID:
		return

	strAddressName = doc.shipping_address_name or doc.customer_address
	if not strAddressName:
		frappe.log_error("DHL Create Recipient Error", "No address found for Sales Order " + doc.name)
		return

	docAddress = frappe.get_doc("Address", strAddressName)

	strCityCode = None
	for row in docDHLSettings.cities:
		if row.city_name and docAddress.city and row.city_name.strip().lower() == docAddress.city.strip().lower():
			strCityCode = row.code
			break

	if not strCityCode:
		frappe.log_error("DHL Create Recipient Error", "City not mapped: " + (docAddress.city or "") + " for SO " + doc.name)
		return

	strDistrictCode = None
	for row in docDHLSettings.districts:
		if (row.city_code == strCityCode
				and row.district_name
				and docAddress.county
				and row.district_name.strip().lower() == docAddress.county.strip().lower()):
			strDistrictCode = row.code
			break

	if not strDistrictCode:
		frappe.log_error("DHL Create Recipient Error", "District not mapped: " + (docAddress.county or "") + " for SO " + doc.name)
		return

	strMobile = docAddress.phone or ""
	strEmail = docAddress.email_id or ""

	if not strMobile:
		strMobile = docDHLSettings.default_phone or ""
	if not strEmail:
		strEmail = docDHLSettings.default_email or ""

	dctTokenResult = get_token()
	if not dctTokenResult.op_result:
		frappe.log_error("DHL Create Recipient Error", "Token failed: " + dctTokenResult.op_message)
		return

	strCreateURL = docDHLSettings.web_service_url + "/mngapi/api/pluscmdapi/createRecipient"

	dctPayload = {
		"recipient": {
			"customerId": "",
			"refCustomerId": doc.customer,
			"cityCode": int(strCityCode),
			"districtCode": int(strDistrictCode),
			"cityName": docAddress.city or "",
			"districtName": docAddress.county or "",
			"address": docAddress.address_line1 or "",
			"fullName": doc.customer_name or "",
			"mobilePhoneNumber": strMobile,
			"bussinessPhoneNumber": "",
			"homePhoneNumber": "",
			"email": strEmail,
			"taxOffice": "",
			"taxNumber": doc.tax_id or ""
		}
	}

	dctHeaders = {
		"x-ibm-client-id": docDHLSettings.client_id,
		"x-ibm-client-secret": docDHLSettings.get_password("client_secret"),
		"Content-Type": "application/json",
		"Authorization": "Bearer " + (docDHLSettings.jwt_token or "")
	}

	try:
		response = requests.post(strCreateURL, json=dctPayload, headers=dctHeaders, timeout=30)
		dctResponse = response.json()

		if docDHLSettings.enable_detailed_logs:
			frappe.log_error("DHL Create Recipient Response", frappe.as_json(dctResponse))

		strNewCustomerId = dctResponse.get("customerId") if isinstance(dctResponse, dict) else None

		if strNewCustomerId:
			docCustomer = frappe.get_doc("Customer", doc.customer)
			docCustomer.dhl_customer_id = strNewCustomerId
			docCustomer.save(ignore_permissions=True)
		else:
			strErrorMessage = ""
			if "error" in dctResponse and isinstance(dctResponse["error"], dict):
				error_dict = dctResponse["error"]
				parts = []
				if error_dict.get("Code"):
					parts.append("Error " + error_dict["Code"])
				if error_dict.get("Message"):
					parts.append(error_dict["Message"])
				if error_dict.get("Description"):
					parts.append(error_dict["Description"])
				strErrorMessage = " - ".join(parts)
			elif "httpMessage" in dctResponse or "moreInformation" in dctResponse:
				strHTTPMessage = dctResponse.get("httpMessage", "")
				strMoreInfo = dctResponse.get("moreInformation", "")
				strErrorMessage = " ".join(filter(None, [strHTTPMessage, strMoreInfo]))
			else:
				strErrorMessage = "Unknown error"

			frappe.log_error("DHL Create Recipient Error", strErrorMessage + " | Response: " + frappe.as_json(dctResponse))
	except Exception:
		frappe.log_error("DHL Create Recipient Error", frappe.get_traceback())