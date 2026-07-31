// Copyright (c) 2026, Logedosoft Business Solutions and contributors
// For license information, please see license.txt

frappe.ui.form.on("Delivery Note", {
	refresh(frm) {
		if (frm.doc.custom_ld_delivery_method !== "DHL") {
			return;
		}

		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("DHL Koli Sayfası Oluştur"), function() {
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
					frm.clear_table("dhl_barcodes");
					for (let i = 0; i < dTotal; i++) {
						let dctRow = frm.add_child("dhl_barcodes");
						dctRow.piece_number = i + 1;
					}
					frm.refresh_field("dhl_barcodes");
				}, __("Koli Bilgisi"));
			}, __("DHL"));
		}

		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("DHL Kargo"), function() {
				let blnGridHasRows = frm.doc.dhl_barcodes && frm.doc.dhl_barcodes.length > 0;

				if (blnGridHasRows) {
					let lstInvalidRows = [];
					for (let dIdx = 0; dIdx < frm.doc.dhl_barcodes.length; dIdx++) {
						let dctRow = frm.doc.dhl_barcodes[dIdx];
						if (flt(dctRow.desi) <= 0 || flt(dctRow.kg) <= 0) {
							lstInvalidRows.push(dIdx + 1);
						}
					}
					if (lstInvalidRows.length > 0) {
						frappe.msgprint({
							title: __("Geçersiz Koli Bilgisi"),
							message: __("Satır {0}: desi ve kg sıfırdan büyük olmalıdır. Lütfen tabloyu düzeltin.", [lstInvalidRows.join(", ")]),
							indicator: "red"
						});
						return;
					}
					let lstParcels = frm.doc.dhl_barcodes.map(function(dctRow) {
						return {desi: flt(dctRow.desi), kg: flt(dctRow.kg)};
					});
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
				} else {
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
				}
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
