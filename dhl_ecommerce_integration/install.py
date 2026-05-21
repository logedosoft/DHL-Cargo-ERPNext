# Copyright (c) 2026, Logedosoft Business Solutions and contributors
# For license information, please see license.txt

import frappe, json
from frappe import msgprint, _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def get_custom_fields():
    return {
        "Customer": [
            {
                "fieldname": "dhl_customer_id",
                "fieldtype": "Data",
                "label": "DHL Customer ID",
                "insert_after": "dn_required",
            }
        ]
        #,"Delivery Note": [
        #    {
        #        "fieldname": "dhl_tracking_number",
        #        "fieldtype": "Data",
        #        "label": "DHL Tracking Number",
        #        "read_only": 1,
        #        "insert_after": "lr_no",  # after LR No field
        #    },
        #],
    }

def after_install():
    create_custom_fields(get_custom_fields(), ignore_validate=True)

def before_uninstall():
    pass
    #for doctype, fields in custom_fields.items():
    #    frappe.db.delete(
    #        "Custom Field",
    #        {
    #            "fieldname": ("in", [f["fieldname"] for f in fields]),
    #            "dt": doctype,
    #        },
    #    )
    #    frappe.clear_cache(doctype=doctype)