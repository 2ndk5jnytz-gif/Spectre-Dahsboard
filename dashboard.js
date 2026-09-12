function showToast(message, ok = true) {
    const toast = document.getElementById("toast");
    toast.textContent = message;
    toast.className = "toast show " + (ok ? "ok" : "err");
    setTimeout(() => { toast.className = "toast"; }, 3200);
}

const GUILD_ID = window.location.pathname.split("/")[2];

async function saveSettings(data) {
    try {
        const response = await fetch(`/dashboard/${GUILD_ID}/save-settings`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });
        const result = await response.json();
        showToast(result.ok ? "✅ تم الحفظ فوراً وانربط بالبوت." : ("❌ " + (result.error || "فشل الحفظ")), result.ok);
        return result;
    } catch (error) {
        showToast("❌ تعذّر الاتصال باللوحة", false);
    }
}

async function callAction(name, payload) {
    try {
        const response = await fetch(`/dashboard/${GUILD_ID}/action/${name}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const result = await response.json();
        showToast(result.ok ? "✅ تم التنفيذ فوراً على البوت." : ("❌ " + (result.error || "فشل التنفيذ")), result.ok);
        return result;
    } catch (error) {
        showToast("❌ تعذّر الاتصال باللوحة", false);
    }
}

function collectForm(formEl) {
    const data = {};
    formEl.querySelectorAll("[data-key]").forEach((el) => {
        data[el.dataset.key] = el.type === "checkbox" ? (el.checked ? "1" : "0") : el.value;
    });
    return data;
}

async function uploadDashboardImage(input, statusEl) {
    const file = input?.files?.[0];
    if (!file) return null;
    if (!file.type.startsWith("image/")) {
        showToast("❌ اختر ملف صورة فقط.", false);
        input.value = "";
        return null;
    }
    if (file.size > 8 * 1024 * 1024) {
        showToast("❌ حجم الصورة يجب ألا يتجاوز 8MB.", false);
        input.value = "";
        return null;
    }
    const data = new FormData();
    data.append("file", file);
    if (statusEl) statusEl.textContent = "جاري رفع الصورة…";
    try {
        const response = await fetch(`/dashboard/${GUILD_ID}/upload-image`, { method: "POST", body: data });
        const result = await response.json();
        if (!result.ok) throw new Error(result.error || "فشل رفع الصورة");
        if (statusEl) statusEl.textContent = `✓ ${result.name}`;
        showToast("✅ تم تجهيز الصورة للنشر.");
        return result;
    } catch (error) {
        if (statusEl) statusEl.textContent = "تعذّر رفع الصورة";
        showToast("❌ " + error.message, false);
        return null;
    }
}

function previewLocalImage(input, imgEl) {
    const file = input?.files?.[0];
    if (!file || !imgEl) return;
    imgEl.src = URL.createObjectURL(file);
    imgEl.style.display = "block";
}


function toggleMobileNav(force){
  const sidebar=document.getElementById('dashboardSidebar');
  const backdrop=document.getElementById('mobileNavBackdrop');
  if(!sidebar || !backdrop) return;
  const open = typeof force === 'boolean' ? force : !sidebar.classList.contains('mobile-open');
  sidebar.classList.toggle('mobile-open', open);
  backdrop.classList.toggle('show', open);
  document.body.classList.toggle('nav-locked', open);
}
document.addEventListener('keydown',e=>{ if(e.key==='Escape') toggleMobileNav(false); });
