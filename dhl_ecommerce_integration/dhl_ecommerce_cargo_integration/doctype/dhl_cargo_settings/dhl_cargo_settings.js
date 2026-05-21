// Copyright (c) 2026, Logedosoft Business Solutions and contributors
// For license information, please see license.txt

frappe.ui.form.on("DHL Cargo Settings", {
	btn_test_connection(frm) {
		//Test the credentials by calling get_token() on utils.py
		frappe.call({
			method: "dhl_ecommerce_integration.utils.get_token",
			callback: function(r) {
				if(r.message) {
					frappe.msgprint(r.message.op_message);
				}
			}
		});
	}
});
