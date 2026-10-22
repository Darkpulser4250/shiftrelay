package org.shiftrelay.probe;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.os.Build;
import android.os.Bundle;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.cert.CertPathValidatorException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLHandshakeException;
import org.json.JSONObject;

/** Native HTTPS client, not a browser and not a modification of other apps. */
public final class MainActivity extends Activity {
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private TextView result;
    private Button run;
    private String report = "No test run yet.";

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        ScrollView scroll = new ScrollView(this);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        layout.setPadding(pad, pad, pad, pad);
        scroll.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(0, insets.getSystemWindowInsetTop(), 0, insets.getSystemWindowInsetBottom());
            return insets;
        });
        TextView title = new TextView(this);
        title.setText("ShiftRelay / Android lab"); title.setTextSize(26);
        layout.addView(title);
        TextView detail = new TextView(this);
        detail.setText("Connect the ShiftRelay WireGuard tunnel, include this app, and install your server's public CA first.\n\nThis native probe tests only our owned HTTPS fixture. Passing does not prove ad removal in YouTube, Netflix, Hulu, Facebook or Instagram. It does not access those apps or your accounts.\n");
        layout.addView(detail);
        run = new Button(this); run.setText("Run native HTTPS test");
        run.setOnClickListener(view -> start()); layout.addView(run);
        Button copy = new Button(this); copy.setText("Copy result for review");
        copy.setOnClickListener(view -> ((ClipboardManager) getSystemService(CLIPBOARD_SERVICE))
            .setPrimaryClip(ClipData.newPlainText("ShiftRelay test result", report)));
        layout.addView(copy);
        result = new TextView(this); result.setTextIsSelectable(true);
        result.setText("Nothing is uploaded. Results stay on this phone unless you copy and share them.");
        layout.addView(result); scroll.addView(layout); setContentView(scroll);
    }

    private static final class Reply {
        int status;
        String body, blocked, fixture;
    }

    private Reply request(String address) throws Exception {
        HttpsURLConnection connection = (HttpsURLConnection) new URL(address).openConnection();
        connection.setConnectTimeout(6000); connection.setReadTimeout(6000);
        connection.setInstanceFollowRedirects(false); connection.setUseCaches(false);
        // Keep the Android TLS verifier and Network Security Config intact.
        try {
            Reply reply = new Reply(); reply.status = connection.getResponseCode();
            reply.blocked = connection.getHeaderField("X-ShiftRelay");
            reply.fixture = connection.getHeaderField("X-ShiftRelay-Lab");
            try (InputStream stream = connection.getInputStream();
                 ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[1024]; int count;
                while ((count = stream.read(buffer)) != -1) {
                    if (bytes.size() + count > 8192) throw new IllegalStateException("Oversize fixture");
                    bytes.write(buffer, 0, count);
                }
                reply.body = new String(bytes.toByteArray(), StandardCharsets.UTF_8);
            }
            return reply;
        } finally { connection.disconnect(); }
    }

    private static boolean trustFailure(Throwable error) {
        // Don't count timeouts, DNS failures or arbitrary SSL errors as a passed control.
        if (!(error instanceof SSLHandshakeException)) return false;
        for (int i = 0; error != null && i < 12; i++, error = error.getCause())
            if (error instanceof CertPathValidatorException) return true;
        return false;
    }

    private void start() {
        run.setEnabled(false); result.setText("Running native HTTPS requests...");
        worker.execute(() -> {
            StringBuilder text = new StringBuilder("ShiftRelay Probe 0.3.0\n");
            text.append("Device: ").append(Build.MANUFACTURER).append(' ').append(Build.MODEL)
                .append("\nAndroid: ").append(Build.VERSION.RELEASE).append(" / API ")
                .append(Build.VERSION.SDK_INT).append('\n');
            long started = android.os.SystemClock.elapsedRealtime();
            boolean content = false, blocked = false, control = false;
            try {
                Reply reply = request("https://relay-test.invalid/content");
                JSONObject object = new JSONObject(reply.body);
                content = reply.status == 200 && "owned-fixture".equals(reply.fixture)
                    && "shiftrelay-owned-content".equals(object.optString("fixture"))
                    && object.optBoolean("preserved");
                text.append("Content preserved: ").append(content ? "PASS" : "FAIL").append('\n');
            } catch (Exception error) {
                text.append("Content: FAIL (").append(error.getClass().getSimpleName()).append(")\n");
            }
            try {
                Reply reply = request("https://relay-test.invalid/ad");
                blocked = reply.status == 204 && "blocked".equals(reply.blocked) && reply.body.isEmpty();
                text.append("Owned ad request blocked: ").append(blocked ? "PASS" : "FAIL").append('\n');
            } catch (Exception error) {
                text.append("Blocking: FAIL (").append(error.getClass().getSimpleName()).append(")\n");
            }
            try {
                request("https://system-test.invalid/content");
                text.append("System-only trust control: UNEXPECTED ACCEPT (check system CA changes)\n");
            } catch (Exception error) {
                control = trustFailure(error);
                text.append("System-only trust control: ")
                    .append(control ? "PASS: private CA rejected" : "INCONCLUSIVE: " + error.getClass().getSimpleName()).append('\n');
            }
            text.append("Elapsed test time: ").append(android.os.SystemClock.elapsedRealtime() - started).append(" ms\n")
                .append("Owned fixture result: ").append(content && blocked && control ? "PASS" : "CHECK RESULTS")
                .append("\nOfficial platform ad removal: NOT TESTED\n");
            report = text.toString();
            runOnUiThread(() -> { if (!isDestroyed()) { result.setText(report); run.setEnabled(true); } });
        });
    }

    @Override public void onDestroy() { worker.shutdownNow(); super.onDestroy(); }
}
