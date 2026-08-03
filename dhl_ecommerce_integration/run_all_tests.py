import frappe
import traceback
import importlib


def execute():
	frappe.flags.in_test = True

	modules = [
		'dhl_ecommerce_integration.tests.test_multi_parcel_barcode',
		'dhl_ecommerce_integration.tests.test_createbarcode_response',
		'dhl_ecommerce_integration.tests.test_sync_barcode_rows',
		'dhl_ecommerce_integration.tests.test_label_pdf_cleanup',
	]

	total = 0
	passed = 0
	failed = 0
	lstErrors = []

	for strModName in modules:
		objMod = importlib.import_module(strModName)
		lstTestFuncs = [getattr(objMod, n) for n in dir(objMod) if n.startswith('test_') and callable(getattr(objMod, n))]
		for objFunc in lstTestFuncs:
			total += 1
			try:
				objFunc()
				passed += 1
				print("PASS  {0}.{1}".format(strModName.split(".")[-1], objFunc.__name__))
			except Exception:
				failed += 1
				strTb = traceback.format_exc()
				lstErrors.append(("{0}.{1}".format(strModName.split(".")[-1], objFunc.__name__), strTb))
				print("FAIL  {0}.{1}".format(strModName.split(".")[-1], objFunc.__name__))

	print("\n--- {0}/{1} passed, {2} failed ---".format(passed, total, failed))
	if lstErrors:
		for strName, strTb in lstErrors:
			print("\n--- {0} ---".format(strName))
			print(strTb)

	return frappe._dict({"total": total, "passed": passed, "failed": failed})
