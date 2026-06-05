// Copyright (c) 2026, Logedosoft Business Solutions and contributors
// For license information, please see license.txt

frappe.ui.form.on("DHL Cargo Settings", {
	btn_test_connection(frm) {
		//Test the credentials by calling get_token() on utils.py
		frappe.call({
			method: "dhl_ecommerce_integration.utils.get_token",
			args: { blnForce: true },
			callback: function(r) {
				if(r.message) {
					frappe.msgprint(r.message.op_message);
				}
			}
		});
	},
	btn_get_cities_and_districts(frm) {
		frappe.call({
			method: "dhl_ecommerce_integration.utils.get_cities_and_districts",
			callback: function(r) {
				if (r.message.op_result == false) {
					frappe.throw(r.message.op_message);
				} else {
					frappe.show_alert(r.message.op_message);
				}
			}
		});
	}
});
