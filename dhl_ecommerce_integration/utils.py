# Copyright (c) 2026, Logedosoft Business Solutions and contributors
# For license information, please see license.txt

import frappe, json, requests
from datetime import datetime
from frappe import msgprint, _
from frappe.utils import get_datetime_str

# Helper function to convert Turkish characters to uppercase for DHL city-district maps
def uppercase_tr(s):
    if not s: 
        return ""
    
    # 1. Translate specific Turkish lowercase letters to uppercase
    tr = str.maketrans("ıişüğçö", "IİŞÜĞÇÖ")
    
    # 2. Apply translation, then standard upper() for the rest (a-z)
    return s.translate(tr).upper()

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

		dctResult.op_result = True
		dctResult.op_message = "DHL Refresh Cities and Districts completed successfully."
		#frappe.log_error("DHL Refresh Cities and Districts", "Completed successfully")
	except Exception:
		dctResult.op_result = False
		dctResult.op_message = "City and District Refresh Failed! " + frappe.get_traceback()
		frappe.log_error("DHL Refresh Cities and Districts Error", dctResult.op_message)
		
	docDHLSettings.add_comment("Comment", dctResult.op_message)

def create_recipient(doc, method):
	# Create the recipient if DHL is active in DHL Cargo Settings
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
				dctResult.op_result = False
				dctResult.op_message = "City not mapped in DHL Cargo Settings: {0}  for Sales Order {1}!".format(docAddress.city or "", doc.name)
				frappe.log_error("DHL Create Recipient Error", dctResult.op_message)
			else:
				strDistrictCode = None
				for row in docDHLSettings.districts:
					if (row.city_code == strCityCode and row.district_name and docAddress.county and row.district_name == docAddress.county):
						strDistrictCode = row.code
						break

				if not strDistrictCode:
					dctResult.op_result = False
					dctResult.op_message = "District not mapped in DHL Cargo Settings: {0} for Sales Order {1}!".format(docAddress.county or "", doc.name)
					frappe.log_error("DHL Create Recipient Error", dctResult.op_message)
				else:
					dctTokenResult = get_token()
					if not dctTokenResult.op_result:
						dctResult.op_result = False
						dctResult.op_message = "Get Token failed: " + dctTokenResult.op_message
						frappe.log_error("DHL Create Recipient Error", dctResult.op_message)
					else:
						strCreateURL = docDHLSettings.web_service_url + "/mngapi/api/pluscmdapi/createRecipient"

						strMobile = docAddress.phone or docDHLSettings.default_phone or ""
						strEmail = docAddress.email_id or docDHLSettings.default_email or ""
						docCustomer = frappe.get_doc("Customer", doc.customer)

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
								"taxOffice": docCustomer.custom_tax_office or "",
								"taxNumber": docCustomer.tax_id or ""
							}
						}

						dctHeaders = {
							"x-ibm-client-id": docDHLSettings.client_id,
							"x-ibm-client-secret": docDHLSettings.get_password("client_secret"),
							"Content-Type": "application/json",
							"Authorization": "Bearer " + (dctTokenResult.token or "")
						}

						try:
							response = requests.post(strCreateURL, json=dctPayload, headers=dctHeaders, timeout=30)

							if docDHLSettings.enable_detailed_logs:
								frappe.log_error("DHL Create Recipient Response", frappe.as_json({
									"status_code": response.status_code,
									"headers": dict(response.headers),
									"body": response.text
								}))

							if response.status_code == 200:
								dctResult.op_result = True
								dctResult.op_message = "Recipient created successfully"
							elif response.status_code == 401:
								# Token may have expired between cache check and API call — force-refresh and retry once
								dctRetryToken = get_token(blnForce=True)
								if dctRetryToken.op_result:
									dctHeaders["Authorization"] = "Bearer " + (dctRetryToken.token or "")
									response = requests.post(strCreateURL, json=dctPayload, headers=dctHeaders, timeout=30)

								if response.status_code == 200:
									dctResult.op_result = True
									dctResult.op_message = "Recipient created successfully (after token refresh)"
								else:
									dctResult.op_result = False
									www_auth = response.headers.get("www-authenticate", "")
									if "invalid_token" in www_auth:
										dctResult.op_message = "Authentication failed: Token expired or invalid. Please re-authenticate."
									else:
										dctResult.op_message = "Authentication failed (401): " + www_auth
									frappe.log_error("DHL Create Recipient HEADER_ERROR", dctResult.op_message)
							elif response.status_code == 404:
								dctResult.op_result = False
								dctResponse = response.json()
								strHTTPMessage = dctResponse.get("httpMessage", "")
								strMoreInfo = dctResponse.get("moreInformation", "")
								strErrorMessage = " ".join(filter(None, [strHTTPMessage, strMoreInfo]))
								dctResult.op_message = "RESPOND_ERROR: " + (strErrorMessage or "Not Found")
								frappe.log_error("DHL Create Recipient RESPOND_ERROR", dctResult.op_message)
							else:
								dctResult.op_result = False
								dctResult.op_message = "HTTP " + str(response.status_code) + ": " + response.text
								frappe.log_error("DHL Create Recipient Error", dctResult.op_message)
						except Exception:
							dctResult.op_result = False
							dctResult.op_message = "Exception occurred during createRecipient call. " + frappe.get_traceback()
							frappe.log_error("DHL Create Recipient Exception", dctResult.op_message)

	doc.add_comment("Comment", dctResult.op_message)
	return dctResult

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