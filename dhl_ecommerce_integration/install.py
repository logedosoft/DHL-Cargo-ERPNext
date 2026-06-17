# Copyright (c) 2026, Logedosoft Business Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


DELIVERY_TYPES = [
    {"code": "Branch Pickup", "delivery_type_id": 2},
    {"code": "Address Delivery", "delivery_type_id": 1},
]

PAYMENT_TYPES = [
    {"code": "Platform Pays", "payment_type_id": 3},
    {"code": "Recipient Pays", "payment_type_id": 2},
    {"code": "Sender Pays", "payment_type_id": 1},
]


def get_custom_fields():
    return {
        "Customer": [
            {
                "fieldname": "dhl_customer_id",
                "fieldtype": "Data",
                "label": "DHL Customer ID",
                "insert_after": "dn_required",
            }
        ],
        "Delivery Note": [
            {
                "fieldname": "dhl_cargo_section",
                "fieldtype": "Section Break",
                "label": "DHL Cargo",
                "insert_after": "sales_team",
            },
            {
                "fieldname": "dhl_reference_id",
                "fieldtype": "Data",
                "label": "DHL Reference ID",
                "read_only": 1,
                "insert_after": "dhl_cargo_section",
            },
            {
                "fieldname": "dhl_order_invoice_id",
                "fieldtype": "Data",
                "label": "DHL Order Invoice ID",
                "read_only": 1,
                "insert_after": "dhl_reference_id",
            },
            {
                "fieldname": "dhl_shipper_branch_code",
                "fieldtype": "Data",
                "label": "DHL Shipper Branch Code",
                "read_only": 1,
                "insert_after": "dhl_order_invoice_id",
            },
            {
                "fieldname": "column_break_dhl1",
                "fieldtype": "Column Break",
                "insert_after": "dhl_shipper_branch_code",
            },
            {
                "fieldname": "dhl_barcode_invoice_id",
                "fieldtype": "Data",
                "label": "DHL Barcode Invoice ID",
                "read_only": 1,
                "insert_after": "column_break_dhl1",
            },
            {
                "fieldname": "dhl_shipment_id",
                "fieldtype": "Data",
                "label": "DHL Shipment ID",
                "read_only": 1,
                "insert_after": "dhl_barcode_invoice_id",
            },
            {
                "fieldname": "dhl_barcodes",
                "fieldtype": "Table",
                "label": "DHL Barcodes",
                "options": "DHL Barcode",
                "insert_after": "dhl_shipment_id",
            },
            {
                "fieldname": "dhl_shipment_status",
                "fieldtype": "Select",
                "label": "DHL Shipment Status",
                "options": "\nPending\nIn Transfer\nIn Transit\nOut for Delivery\nDelivered\nDelivery Failed\nReturning\nSupport Needed\nNot Found",
                "read_only": 1,
                "allow_on_submit": 1,
                "insert_after": "dhl_barcodes",
            },
            {
                "fieldname": "dhl_last_tracked",
                "fieldtype": "Datetime",
                "label": "DHL Last Tracked",
                "read_only": 1,
                "allow_on_submit": 1,
                "insert_after": "dhl_shipment_status",
            },
        ],
    }


def after_install():
    run_install_setup()


def after_sync():
    run_install_setup()


def before_uninstall():
    pass


def run_install_setup():
    create_custom_fields(get_custom_fields(), ignore_validate=True)
    ensure_delivery_method_has_dhl()
    seed_dhl_delivery_types()
    seed_dhl_payment_types()
    frappe.db.commit()


def ensure_delivery_method_has_dhl():
    doctype = "Delivery Note"
    fieldname = "custom_ld_delivery_method"
    new_option = "DHL"

    if not frappe.db.exists("DocType", doctype):
        frappe.log_error(
            title="DHL Integration Install Warning",
            message=f"DocType {doctype} does not exist on this site. Skipping DHL option setup.",
        )
        return

    custom_field_name = frappe.db.get_value(
        "Custom Field",
        {"dt": doctype, "fieldname": fieldname},
        "name",
    )

    if custom_field_name:
        custom_field = frappe.get_doc("Custom Field", custom_field_name)
        has_leading_blank, options = split_options(custom_field.options)

        if new_option not in options:
            custom_field.options = build_options(has_leading_blank, options + [new_option])
            custom_field.save(ignore_permissions=True)
            frappe.clear_cache(doctype=doctype)

        return

    docfield = frappe.get_meta(doctype).get_field(fieldname)

    if not docfield:
        frappe.log_error(
            title="DHL Integration Install Warning",
            message=f"{doctype}.{fieldname} was not found while trying to add DHL option.",
        )
        return

    has_leading_blank, options = split_options(docfield.options)

    if new_option in options:
        return

    new_value = build_options(has_leading_blank, options + [new_option])

    property_setter_name = frappe.db.get_value(
        "Property Setter",
        {
            "doc_type": doctype,
            "field_name": fieldname,
            "property": "options",
        },
        "name",
    )

    if property_setter_name:
        property_setter = frappe.get_doc("Property Setter", property_setter_name)
        property_setter.value = new_value
        property_setter.save(ignore_permissions=True)
    else:
        frappe.get_doc(
            {
                "doctype": "Property Setter",
                "doc_type": doctype,
                "doctype_or_field": "DocField",
                "field_name": fieldname,
                "property": "options",
                "property_type": "Text",
                "value": new_value,
            }
        ).insert(ignore_permissions=True)

    frappe.clear_cache(doctype=doctype)


def split_options(options):
    """Returns (has_leading_blank, list_of_non_empty_options).
    Preserves the leading empty line that Select fields use for a blank default.
    """
    raw = (options or "").split("\n")
    has_leading_blank = len(raw) > 0 and raw[0].strip() == ""
    non_empty = [row.strip() for row in raw if row.strip()]
    return has_leading_blank, non_empty


def build_options(has_leading_blank, options):
    """Rebuilds the options string, re-adding the leading blank if it was present."""
    result = "\n".join(options)
    if has_leading_blank:
        result = "\n" + result
    return result


def seed_dhl_delivery_types():
    upsert_records(
        doctype="DHL Delivery Type",
        records=DELIVERY_TYPES,
        lookup_field="code",
        update_fields=["delivery_type_id"],
    )


def seed_dhl_payment_types():
    upsert_records(
        doctype="DHL Payment Type",
        records=PAYMENT_TYPES,
        lookup_field="code",
        update_fields=["payment_type_id"],
    )


def upsert_records(doctype, records, lookup_field, update_fields):
    for row in records:
        filters = {lookup_field: row[lookup_field]}
        existing_name = frappe.db.get_value(doctype, filters, "name")

        if existing_name:
            doc = frappe.get_doc(doctype, existing_name)
            changed = False

            for fieldname in update_fields:
                if doc.get(fieldname) != row.get(fieldname):
                    doc.set(fieldname, row.get(fieldname))
                    changed = True

            if changed:
                doc.save(ignore_permissions=True)
        else:
            frappe.get_doc(
                {
                    "doctype": doctype,
                    **row,
                }
            ).insert(ignore_permissions=True)
