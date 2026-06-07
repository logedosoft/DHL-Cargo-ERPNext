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
        ]
        #,"Delivery Note": [
        #    {
        #        "fieldname": "dhl_tracking_number",
        #        "fieldtype": "Data",
        #        "label": "DHL Tracking Number",
        #        "read_only": 1,
        #        "insert_after": "lr_no",
        #    },
        #],
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


def ensure_delivery_method_has_dhl():
    doctype = "Delivery Method"
    fieldname = "custom_ld_delivery_method"
    new_option = "DHL"

    custom_field_name = frappe.db.get_value(
        "Custom Field",
        {"dt": doctype, "fieldname": fieldname},
        "name",
    )

    if custom_field_name:
        custom_field = frappe.get_doc("Custom Field", custom_field_name)
        options = split_options(custom_field.options)

        if new_option not in options:
            custom_field.options = "\n".join(options + [new_option])
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

    options = split_options(docfield.options)

    if new_option in options:
        return

    new_value = "\n".join(options + [new_option])

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
    return [row.strip() for row in (options or "").split("\n") if row.strip()]


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
