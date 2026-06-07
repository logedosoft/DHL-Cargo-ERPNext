# Copyright (c) 2026, Logedosoft Business Solutions and contributors
# For license information, please see license.txt

import frappe


def execute():
    from dhl_ecommerce_integration.install import run_install_setup

    run_install_setup()
    frappe.db.commit()
