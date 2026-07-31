# Copyright (c) 2026, Logedosoft Business Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import today

from dhl_ecommerce_integration.utils import (
	_build_create_return_order_payload,
	_send_create_return_order,
	get_token,
	uppercase_tr,
)


class DHLReturnOrder(Document):
	pass


@frappe.whitelist()
def create_return_order(docname=None, sales_order_name=None, item_code=None, return_qty=None):
	dctResult = frappe._dict({
		"op_result": False,
		"op_message": "",
		"reference_id": "",
		"return_label_url": "",
		"dhl_return_order_name": "",
	})

	if not frappe.has_permission("DHL Return Order", "create"):
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)

	docDHLSettings = frappe.get_single("DHL Cargo Settings")
	if not docDHLSettings.enabled:
		dctResult.op_message = "DHL Cargo Settings is not enabled"
		frappe.log_error("DHL Create Return Order", dctResult.op_message)
		return dctResult

	docReturn = None
	if docname:
		docReturn = frappe.get_doc("DHL Return Order", docname)
		docSO = frappe.get_doc("Sales Order", docReturn.sales_order)
		strItemCode = docReturn.item_code
		dReturnQty = int(docReturn.return_qty)
	else:
		if not sales_order_name or not item_code or not return_qty:
			dctResult.op_message = "sales_order_name, item_code, and return_qty are required"
			return dctResult

		dReturnQty = int(return_qty)
		docSO = frappe.get_doc("Sales Order", sales_order_name)
		strItemCode = item_code

	# --- shared validation ---
	dctValidation = _validate_return_request(docSO.name, strItemCode, dReturnQty)
	if not dctValidation.op_result:
		dctResult.op_message = dctValidation.op_message
		return dctResult

	# --- active duplicate check (exclude self when re-triggering an existing record) ---
	dctFilters = {
		"sales_order": docSO.name,
		"item_code": strItemCode,
		"status": ["in", ["Pending", "Order Created", "In Transit"]],
	}
	if docReturn:
		dctFilters["name"] = ["!=", docReturn.name]
	existing = frappe.db.get_value("DHL Return Order", dctFilters, "name")
	if existing:
		frappe.throw("A return order already exists: {0}".format(existing))

	# --- create doc only for new records ---
	if not docReturn:
		docReturn = frappe.get_doc({
			"doctype": "DHL Return Order",
			"sales_order": docSO.name,
			"customer": docSO.customer,
			"item_code": strItemCode,
			"return_qty": dReturnQty,
			"status": "Pending",
			"shipper_name": docSO.customer_name or "",
			"reference_id": "",
			"barcode": "",
		})
		docReturn.insert()

	strCustomerNumber = docDHLSettings.customer_number or ""
	if not strCustomerNumber:
		dctResult.op_message = "DHL customer number is not configured in DHL Cargo Settings"
		frappe.log_error("DHL Create Return Order", dctResult.op_message)
		return dctResult

	docAddress = _get_shipping_address(docSO)
	if not docAddress:
		dctResult.op_message = "Shipping address not found for Sales Order {0}".format(docSO.name)
		frappe.log_error("DHL Create Return Order", dctResult.op_message)
		return dctResult

	dctTokenResult = get_token()
	if not dctTokenResult.op_result:
		dctResult.op_message = "Get Token failed: " + dctTokenResult.op_message
		frappe.log_error("DHL Create Return Order", dctResult.op_message)
		return dctResult

	strReferenceId = _generate_reference_id()
	dctPayload = _build_create_return_order_payload(
		strReferenceId, docSO, docAddress,
		strItemCode, dReturnQty, docDHLSettings
	)
	dctHeaders = {
		"x-ibm-client-id": docDHLSettings.client_id,
		"x-ibm-client-secret": docDHLSettings.get_password("client_secret"),
		"Content-Type": "application/json",
		"Authorization": "Bearer " + dctTokenResult.token,
	}
	strURL = docDHLSettings.web_service_url + "/mngapi/api/standardcmdapi/createReturnOrder"
	dctAPICallResult = _send_create_return_order(dctPayload, dctHeaders, strURL, docDHLSettings)

	# Retry once on 401 (token may have expired between fetch and call)
	if not dctAPICallResult.op_result and getattr(dctAPICallResult, 'status_code', 0) == 401:
		dctTokenResult2 = get_token(blnForce=True)
		if dctTokenResult2.op_result:
			dctHeaders["Authorization"] = "Bearer " + dctTokenResult2.token
			dctAPICallResult = _send_create_return_order(dctPayload, dctHeaders, strURL, docDHLSettings)

	if not dctAPICallResult.op_result:
		dctResult.op_message = dctAPICallResult.op_message
		frappe.log_error("DHL Create Return Order API Failed", dctResult.op_message)
		return dctResult

	strReturnLabelURL = dctAPICallResult.return_label_url or ""
	if not strReturnLabelURL:
		frappe.log_error(
			"DHL Create Return Order",
			"createReturnOrder succeeded but returnOrderLabelURL was empty"
		)
		frappe.msgprint("Return order created but label URL was not provided.")

	docReturn.reload()
	frappe.db.set_value("DHL Return Order", docReturn.name, {
		"reference_id": dctAPICallResult.reference_id or strReferenceId,
		"barcode": dctAPICallResult.reference_id or strReferenceId,
		"invoice_id": dctAPICallResult.order_invoice_id or "",
		"return_label_url": strReturnLabelURL,
		"status": "Order Created",
		"shipper_phone": _get_customer_phone(docAddress),
		"shipper_email": _get_customer_email(docAddress),
		"shipper_city": uppercase_tr(docAddress.city or ""),
		"shipper_district": uppercase_tr(docAddress.county or ""),
		"shipper_address": _format_address(docAddress),
	})

	dctResult.op_result = True
	dctResult.op_message = "Return order created successfully"
	dctResult.reference_id = dctAPICallResult.reference_id or strReferenceId
	dctResult.return_label_url = strReturnLabelURL
	dctResult.dhl_return_order_name = docReturn.name

	return dctResult


def _validate_return_request(strSalesOrderName, strItemCode, dReturnQty):
	dctResult = frappe._dict({"op_result": True, "op_message": ""})

	docSO = frappe.get_doc("Sales Order", strSalesOrderName)
	if docSO.docstatus != 1:
		dctResult.op_result = False
		dctResult.op_message = "Sales Order must be submitted"
	elif dReturnQty <= 0:
		dctResult.op_result = False
		dctResult.op_message = "Return quantity must be greater than zero"
	else:
		blnItemFound = False
		for docItem in docSO.items:
			if docItem.item_code == strItemCode:
				blnItemFound = True
				if docItem.qty < dReturnQty:
					dctResult.op_result = False
					dctResult.op_message = "Return quantity {0} exceeds ordered quantity {1}".format(dReturnQty, docItem.qty)
				break

		if dctResult.op_result and not blnItemFound:
			dctResult.op_result = False
			dctResult.op_message = "Item {0} not found in Sales Order {1}".format(strItemCode, strSalesOrderName)

	return dctResult


def _generate_reference_id():
	strDate = today().replace("-", "")
	strPrefix = "RET{0}".format(strDate)
	intCount = frappe.db.count(
		"DHL Return Order",
		filters={"reference_id": ["like", "{0}%".format(strPrefix)]}
	)
	strReferenceId = "{0}{1:05d}".format(strPrefix, intCount + 1)
	return strReferenceId[:20].upper()


def _get_shipping_address(docSO):
	docAddress = None
	if docSO.shipping_address_name:
		try:
			docAddress = frappe.get_doc("Address", docSO.shipping_address_name)
		except Exception:
			pass
	return docAddress


def _get_customer_phone(docAddress):
	strPhone = docAddress.phone or ""
	if not strPhone:
		docDHLSettings = frappe.get_single("DHL Cargo Settings")
		strPhone = docDHLSettings.default_phone or ""
	return strPhone


def _get_customer_email(docAddress):
	strEmail = docAddress.email_id or ""
	if not strEmail:
		docDHLSettings = frappe.get_single("DHL Cargo Settings")
		strEmail = docDHLSettings.default_email or ""
	return strEmail


def _format_address(docAddress):
	lstParts = []
	if docAddress.address_line1:
		lstParts.append(docAddress.address_line1)
	if docAddress.address_line2:
		lstParts.append(docAddress.address_line2)
	return " ".join(lstParts).strip()
