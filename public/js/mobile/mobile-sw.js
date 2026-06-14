if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").then(function(reg) {
    console.log("SW registered:", reg.scope);
    reg.addEventListener("updatefound", function() {
      var worker = reg.installing;
      worker.addEventListener("statechange", function() {
        if (worker.state === "activated" && navigator.serviceWorker.controller) {
          var toast = document.createElement("div");
          toast.style.cssText = "position:fixed;top:0;left:0;right:0;background:#4F46E5;color:#fff;text-align:center;padding:8px;z-index:9999;cursor:pointer";
          toast.textContent = "有新版本，点击刷新";
          toast.addEventListener("click", function() { location.reload(); });
          document.body.appendChild(toast);
          setTimeout(function() { toast.remove(); }, 5000);
        }
      });
    });
  }).catch(function(e) { console.log("SW failed:", e); });

  // Offline indicator
  window.addEventListener("online", function() {
    var bar = document.getElementById("offline-bar");
    if (bar) bar.remove();
  });
  window.addEventListener("offline", function() {
    var bar = document.createElement("div");
    bar.id = "offline-bar";
    bar.style.cssText = "position:fixed;top:0;left:0;right:0;background:#F59E0B;color:#fff;text-align:center;padding:6px;z-index:9999;font-size:14px";
    bar.textContent = "当前离线 - 数据将在恢复网络后同步";
    document.body.appendChild(bar);
  });
  if (!navigator.onLine) {
    window.dispatchEvent(new Event("offline"));
  }
}