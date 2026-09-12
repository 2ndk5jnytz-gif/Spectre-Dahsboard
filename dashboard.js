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

async function uploadDashboardImage(inputEl, targetElOrSetter, buttonEl) {
    const file = inputEl && inputEl.files && inputEl.files[0];
    if (!file) return;
    if (!file.type.startsWith('image/')) { showToast('❌ اختر ملف صورة فقط', false); inputEl.value=''; return; }
    if (file.size > 8 * 1024 * 1024) { showToast('❌ الحد الأقصى للصورة 8MB', false); inputEl.value=''; return; }
    if (buttonEl) { buttonEl.disabled = true; buttonEl.textContent = '⏳ جارٍ الرفع...'; }
    try {
        const form = new FormData();
        form.append('file', file);
        const response = await fetch(`/dashboard/${GUILD_ID}/upload-image`, {method:'POST', body:form});
        const result = await response.json();
        if (!result.ok) throw new Error(result.error || 'فشل رفع الصورة');
        if (typeof targetElOrSetter === 'function') targetElOrSetter(result.url);
        else if (targetElOrSetter) targetElOrSetter.value = result.url;
        showToast('✅ تم رفع الصورة وحفظ رابطها من Discord', true);
        if (targetElOrSetter && targetElOrSetter.dispatchEvent) targetElOrSetter.dispatchEvent(new Event('input', {bubbles:true}));
    } catch (e) { showToast('❌ '+e.message, false); }
    finally { if (buttonEl) { buttonEl.disabled=false; buttonEl.textContent='📱 رفع من الهاتف'; } inputEl.value=''; }
}

function imageUploadControls(targetId, setterCode='') {
    const target = document.getElementById(targetId);
    if (!target) return '';
    return `<div class="upload-row"><input type="file" accept="image/png,image/jpeg,image/gif,image/webp" id="${targetId}-file" hidden onchange="uploadDashboardImage(this, ${setterCode || 'document.getElementById(\''+targetId+'\')'}, this.nextElementSibling)"><button type="button" class="btn btn-ghost" onclick="document.getElementById('${targetId}-file').click()">📱 رفع من الهاتف</button></div>`;
}
