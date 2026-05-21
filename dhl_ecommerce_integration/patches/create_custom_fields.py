# Copyright (c) 2026, Logedosoft Business Solutions and contributors
# For license information, please see license.txt

def execute():
    from dhl_ecommerce_integration.install import get_custom_fields
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields(get_custom_fields(), ignore_validate=True)