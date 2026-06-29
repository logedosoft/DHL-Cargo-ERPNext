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
								method: "dhl_ecommerce_integration.utils.create_barcode",
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
			if (frm.doc.dhl_barcodes && frm.doc.dhl_barcodes.length > 0) {
				frm.add_custom_button(__("DHL Etiket PDF"), function() {
					frappe.call({
						method: "dhl_ecommerce_integration.utils.generate_dhl_pdfs",
						args: { strDeliveryNoteName: frm.docname },
						freeze: true,
						freeze_message: __("DHL etiket PDF'leri oluşturuluyor..."),
						callback: function(dctR) {
							if (dctR.message) {
								if (dctR.message.op_result) {
									frappe.show_alert(__("{0} PDF dosyası eklendi", [dctR.message.lst_file_urls.length]));
								} else {
									frappe.msgprint(__("Hata: {0}", [dctR.message.op_message]));
								}
							}
							frm.reload_doc();
						}
					});
				}, __("Kargo Etiketi Yazdır"));
			}
			if (frm.doc.dhl_reference_id) {
				frm.add_custom_button(__("DHL Kargo İptal Et"), function() {
					frappe.confirm(
						__("{0} numaralı DHL kargosu iptal edilecek. Emin misiniz?", [frm.doc.dhl_reference_id]),
						function() {
							frappe.call({
								method: "dhl_ecommerce_integration.utils.cancel_dhl_order",
								args: { strReferenceId: frm.doc.dhl_reference_id },
								freeze: true,
								freeze_message: __("DHL kargosu iptal ediliyor..."),
								callback: function(dctR) {
									if (dctR.message) {
										if (dctR.message.op_result) {
											frappe.show_alert(__("DHL kargosu iptal edildi."));
										} else {
											frappe.msgprint(__("Hata: {0}", [dctR.message.op_message]));
										}
									}
									frm.reload_doc();
								}
							});
						}
					);
				}, __("Kargo Etiketi Yazdır"));
			}
		}
	}
});
