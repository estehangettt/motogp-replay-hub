package com.estehangettt.motogpreplayhub;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;

/** Pembungkus WebView untuk server Flask lokal di Termux. */
public class MainActivity extends Activity {

    private static final String APP_URL = "http://127.0.0.1:5000";
    private static final String APP_HOST = "127.0.0.1";
    private static final String OFFLINE_URL = "file:///android_asset/offline.html";

    private FrameLayout root;
    private WebView webView;
    private final FullscreenClient chromeClient = new FullscreenClient();
    private View fullscreenView;
    private WebChromeClient.CustomViewCallback fullscreenCallback;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        root = new FrameLayout(this);
        webView = new WebView(this);
        webView.setBackgroundColor(Color.parseColor("#09090B"));
        root.addView(webView, matchParent());
        setContentView(root);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setAllowFileAccess(false);

        webView.setWebViewClient(new LocalClient());
        webView.setWebChromeClient(chromeClient);
        webView.loadUrl(APP_URL);
    }

    private static FrameLayout.LayoutParams matchParent() {
        return new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
    }

    private final class LocalClient extends WebViewClient {
        /** Tautan di luar server lokal dibuka di browser. */
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            if (APP_HOST.equals(uri.getHost())) {
                return false;
            }
            if ("https".equals(uri.getScheme())) {
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri));
                } catch (ActivityNotFoundException error) {
                    Toast.makeText(MainActivity.this, "Tidak ada browser", Toast.LENGTH_SHORT).show();
                }
            }
            return true;
        }

        /** Server Termux belum jalan: tampilkan petunjuk dan tombol coba lagi. */
        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame()) {
                view.loadUrl(OFFLINE_URL);
            }
        }
    }

    private final class FullscreenClient extends WebChromeClient {
        @Override
        public void onShowCustomView(View view, CustomViewCallback callback) {
            if (fullscreenView != null) {
                callback.onCustomViewHidden();
                return;
            }
            fullscreenView = view;
            fullscreenCallback = callback;
            view.setBackgroundColor(Color.BLACK);
            root.addView(view, matchParent());
            webView.setVisibility(View.GONE);
            setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            setImmersive(true);
        }

        @Override
        public void onHideCustomView() {
            if (fullscreenView == null) {
                return;
            }
            root.removeView(fullscreenView);
            fullscreenView = null;
            webView.setVisibility(View.VISIBLE);
            setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);
            getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            setImmersive(false);
            // Kosongkan dulu agar aman bila callback memanggil method ini lagi.
            CustomViewCallback callback = fullscreenCallback;
            fullscreenCallback = null;
            callback.onCustomViewHidden();
        }
    }

    @SuppressWarnings("deprecation")
    private void setImmersive(boolean immersive) {
        getWindow().getDecorView().setSystemUiVisibility(immersive
                ? View.SYSTEM_UI_FLAG_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                : View.SYSTEM_UI_FLAG_VISIBLE);
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (fullscreenView != null) {
            chromeClient.onHideCustomView();
            return;
        }
        webView.evaluateJavascript("Boolean(window.appBack && window.appBack())", handled -> {
            if (!"true".equals(handled)) {
                finish();
            }
        });
    }

    @Override
    protected void onPause() {
        webView.onPause();
        super.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        webView.onResume();
    }

    @Override
    protected void onDestroy() {
        root.removeView(webView);
        webView.destroy();
        super.onDestroy();
    }
}
