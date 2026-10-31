package org.amirtest.bridge;

import android.app.Activity;
import com.google.android.gms.tasks.OnCanceledListener;
import com.google.android.gms.tasks.OnFailureListener;
import com.google.android.gms.tasks.OnSuccessListener;
import com.google.mlkit.vision.barcode.common.Barcode;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanner;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning;

public class QrBridge {
    private static String status = "idle";
    private static String result = "";

    public static synchronized String getStatus() { return status; }
    public static synchronized String getResult() { return result; }
    private static synchronized void set(String s, String r) {
        status = s;
        result = r;
    }

    public static void scan(final Activity activity) {
        set("scanning", "");
        activity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                try {
                    GmsBarcodeScanner scanner =
                        GmsBarcodeScanning.getClient(activity);
                    scanner.startScan()
                        .addOnSuccessListener(new OnSuccessListener<Barcode>() {
                            @Override
                            public void onSuccess(Barcode barcode) {
                                String v = barcode.getRawValue();
                                set("ok", v == null ? "" : v);
                            }
                        })
                        .addOnCanceledListener(new OnCanceledListener() {
                            @Override
                            public void onCanceled() {
                                set("canceled", "");
                            }
                        })
                        .addOnFailureListener(new OnFailureListener() {
                            @Override
                            public void onFailure(Exception e) {
                                set("error: " + e, "");
                            }
                        });
                } catch (Exception e) {
                    set("error: " + e, "");
                }
            }
        });
    }
}
