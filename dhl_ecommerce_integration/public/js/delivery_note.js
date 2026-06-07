// Copyright (c) 2026, Logedosoft Business Solutions and contributors
// For license information, please see license.txt

frappe.ui.form.on("Delivery Note", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.custom_ld_delivery_method === "DHL") {
			frm.add_custom_button(__("DHL Kargo"), function() {
				frappe.prompt({
					label: __("Fiziksel Koli Adedi"),
					fieldname: "dParcelCount",
					fieldtype: "Int",
					reqd: 1
				}, function(dctValues) {
					let dTotal = dctValues.dParcelCount;
					if (dTotal <= 0) {
						frappe.msgprint(__("Koli adedi sıfırdan büyük olmalıdır!"));
						return;
					}
					let lstParcels = [];
					function askParcel(dIdx) {
						if (dIdx >= dTotal) {
							frappe.call({
								method: "dhl_ecommerce_integration.utils.create_order",
								args: {
									strDeliveryNoteName: frm.docname,
									lstParcels: lstParcels
								},
								freeze: true,
								freeze_message: __("DHL etiket oluşturuluyor..."),
								callback: function(dctR) {
									if (dctR.message) {
										if (dctR.message.op_result) {
											let strMsg = __("DHL etiket başarıyla oluşturuldu");
											if (dctR.message.barcodes && dctR.message.barcodes.length > 0) {
												strMsg += __(" — {0} etiket üretildi", [dctR.message.barcodes.length]);
											}
											frappe.show_alert(strMsg);
										} else {
											frappe.msgprint(__("Hata: {0}", [dctR.message.op_message]));
										}
									}
									frm.reload_doc();
								}
							});
							return;
						}
						frappe.prompt([
							{
								label: __("Paket {0} Desi").replace("{0}", dIdx + 1),
								fieldname: "flDesi",
								fieldtype: "Float",
								reqd: 1
							},
							{
								label: __("Paket {0} Kg").replace("{0}", dIdx + 1),
								fieldname: "flKg",
								fieldtype: "Float",
								reqd: 1
							}
						], function(dctParcelValues) {
							lstParcels.push({
								desi: dctParcelValues.flDesi,
								kg: dctParcelValues.flKg
							});
							askParcel(dIdx + 1);
						}, __("Paket {0}/{1}").replace("{0}", dIdx + 1).replace("{1}", dTotal));
					}
					askParcel(0);
				}, __("Koli Bilgisi"));
			}, __("Kargo Etiketi Yazdır"));
		}
	}
});
