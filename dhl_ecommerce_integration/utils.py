# Copyright (c) 2026, Logedosoft Business Solutions and contributors
# For license information, please see license.txt

import frappe, json, requests
from datetime import datetime
from frappe import msgprint, _
from frappe.utils import get_datetime_str

@frappe.whitelist()
def get_token():
	dctResult = frappe._dict({
		"op_result": False,
		"op_message": ""
	})

	docDHLSettings = frappe.get_single("DHL Cargo Settings")
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
			strExpireDate = dctResponse.get("jwtExpireDate")
			if strExpireDate:
				docDHLSettings.jwt_expire_date = datetime.strptime(strExpireDate, "%d.%m.%Y %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")#get_datetime_str(datetime.strptime(strExpireDate, "%d.%m.%Y %H:%M:%S"))
			docDHLSettings.save(ignore_permissions=True)
			dctResult.op_result = True
			dctResult.op_message = _("Token obtained")
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

def create_recipient(doc, method):
	# Create the recipient if DHL is active in DHL Cargo Settings
	# Check if we already have a "dhl_customer_id" for the customer.
	frappe.log_error("DHL Create Recipient", frappe.as_json(doc))
	docDHLSettings = frappe.get_single("DHL Cargo Settings")
	if docDHLSettings.enabled == 1:
		frappe.log_error("DHL Recipient Created", frappe.as_json(doc))
		strDHLCustomerID = frappe.db.get_value("Customer", doc.name, "dhl_customer_id")
		if strDHLCustomerID == None or strDHLCustomerID == "":
			# Create the recipient
			frappe.log_error("DHL Recipient Created", frappe.as_json(doc))
	else:
		frappe.log_error("DHL Recipient Already Exists", frappe.as_json(doc))