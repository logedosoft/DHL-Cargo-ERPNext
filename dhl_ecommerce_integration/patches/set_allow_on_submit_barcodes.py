import frappe


def execute():
	frappe.db.set_value(
		"Custom Field",
		{"dt": "Delivery Note", "fieldname": "dhl_barcodes"},
		"allow_on_submit",
		1,
	)
