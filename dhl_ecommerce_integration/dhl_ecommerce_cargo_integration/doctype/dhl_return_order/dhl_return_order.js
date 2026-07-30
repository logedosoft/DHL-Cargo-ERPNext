// Copyright (c) 2026, Logedosoft Business Solutions and contributors
// For license information, please see license.txt

frappe.ui.form.on("DHL Return Order", {
	refresh(frm) {
		if (frm.doc.status === "Pending" && !frm.doc.reference_id) {
			frm.add_custom_button(__("Create Return Order"), function () {
				frm.save().then(function () {
					frappe.call({
						method: "dhl_ecommerce_integration.dhl_ecommerce_cargo_integration.doctype.dhl_return_order.dhl_return_order.create_return_order",
						args: {
							docname: frm.doc.name,
							sales_order_name: frm.doc.sales_order,
							item_code: frm.doc.item_code,
							return_qty: frm.doc.return_qty,
						},
						freeze: true,
						freeze_message: __("Creating DHL return order..."),
						callback: function (r) {
							if (r.message && r.message.op_result) {
								frm.reload_doc();
								frappe.show_alert({
									indicator: "green",
									message: __("Return order created: {0}", [r.message.reference_id]),
								});
							} else {
								frappe.msgprint({
									title: __("Error"),
									indicator: "red",
									message: r.message ? r.message.op_message : __("Unknown error"),
								});
							}
						},
						error: function (r) {
							frappe.msgprint({
								title: __("Error"),
								indicator: "red",
								message: r.message || __("Network error"),
							});
						},
					});
				});
			}, __("DHL Actions"));
		}

		if (["Order Created", "In Transit"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Track Status"), function () {
				frappe.call({
					method: "dhl_ecommerce_integration.utils.check_return_status",
					args: {
						strDHLReturnOrderName: frm.doc.name,
					},
					freeze: true,
					freeze_message: __("Checking return status..."),
					callback: function (r) {
						if (r.message && r.message.op_result) {
							frappe.show_alert({
								indicator: "green",
								message: __("Status: {0}", [r.message.op_message]),
							});
							frm.reload_doc();
						} else {
							frappe.msgprint({
								title: __("Error"),
								indicator: "red",
								message: r.message ? r.message.op_message : __("Unknown error"),
							});
						}
					},
					error: function (r) {
						frappe.msgprint({
							title: __("Error"),
							indicator: "red",
							message: r.message || __("Network error"),
						});
					},
				});
			}, __("DHL Actions"));
		}

		if (frm.doc.return_label_url) {
			frm.add_custom_button(__("Open Return Label"), function () {
				window.open(frm.doc.return_label_url, "_blank");
			}, __("DHL Actions"));
		}
	},
});
