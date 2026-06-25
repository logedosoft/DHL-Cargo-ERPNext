// Copyright (c) 2026, Logedosoft Business Solutions and contributors
// For license information, please see license.txt

frappe.ui.form.on("DHL Cargo Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Cancel Order"), function() {
			frappe.prompt({
				label: __("DHL Reference ID"),
				fieldname: "strReferenceId",
				fieldtype: "Data",
				reqd: 1
			}, function(dctValues) {
				let strRef = dctValues.strReferenceId.trim().toUpperCase();
				frappe.confirm(
					__("Cancel DHL shipment {0}? This cannot be undone.", [strRef]),
					function() {
						frappe.call({
							method: "dhl_ecommerce_integration.utils.cancel_dhl_order",
							args: { strReferenceId: strRef },
							freeze: true,
							freeze_message: __("Cancelling DHL shipment {0}...", [strRef]),
							callback: function(dctR) {
								if (dctR.message) {
									if (dctR.message.op_result) {
										frappe.show_alert(__("DHL shipment {0} cancelled.", [strRef]));
									} else {
										frappe.msgprint(__("Error: {0}", [dctR.message.op_message]));
									}
								}
							}
						});
					}
				);
			}, __("Cancel DHL Shipment"));
		}, __("Cargo Operations"));
	},
	btn_test_connection(frm) {
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
