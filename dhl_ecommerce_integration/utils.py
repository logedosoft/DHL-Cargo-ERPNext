# Copyright (c) 2026, Logedosoft Business Solutions and contributors
# For license information, please see license.txt

import frappe, json
from frappe import msgprint, _

def get_token():
	dctResult = frappe._dict({
		"op_result": False,
		"op_message": ""
	}
	

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