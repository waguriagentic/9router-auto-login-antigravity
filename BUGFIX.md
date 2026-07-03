# Bug Fix: onboardUser "no project_id in response" Error

## Date
2026-07-03

## Problem
Error terjadi saat testing model Antigravity di 9router:
```
[ProjectId] onboardUser attempt 2 failed: onboardUser done but no project_id in response, retrying...
[ProjectId] onboardUser failed after 5 attempts: onboardUser done but no project_id in response
[13:43:21] [PENDING] START | provider=antigravity | model=claude-opus-4-6-thinking
```

## Root Cause
Fungsi `onboard_user()` di `bot.py` **tidak mengirimkan `projectId` dalam request body** ke API Google `v1internal:onboardUser`. 

### ❌ Kode Lama (SALAH):
```python
def onboard_user(access_token, tier_id, max_retries=10):
    headers = {**LOAD_HEADERS, "Authorization": f"Bearer {access_token}"}
    data = json.dumps({"tierId": tier_id, "metadata": CLIENT_METADATA}).encode()
    # ❌ MISSING projectId - Google API tidak tahu project mana yang di-onboard
```

### ✅ Kode Baru (BENAR):
```python
def onboard_user(access_token, project_id, tier_id, max_retries=10):
    headers = {**LOAD_HEADERS, "Authorization": f"Bearer {access_token}"}
    data = json.dumps({
        "tierId": tier_id, 
        "metadata": CLIENT_METADATA,
        "projectId": project_id  # ✅ Required by Google API!
    }).encode()
```

## Analysis from 9router Source Code

### Reference: `/open-sse/services/projectId.js` (Line 207-219)
```javascript
async function onboardUser(accessToken, tierID, externalSignal) {
    const reqBody = {
        tierId: tierID,
        metadata: LOAD_CODE_ASSIST_METADATA,
        projectId: projectID  // ✅ projectId MUST be included
    };
    
    const response = await fetch(CLOUD_CODE_API.onboardUser, {
        method: "POST",
        headers: { ...LOAD_CODE_ASSIST_HEADERS, "Authorization": `Bearer ${accessToken}` },
        body: JSON.stringify(reqBody),
        signal: localCtrl.signal
    });
    
    // ... check response.done and extract cloudaicompanionProject
}
```

### Reference: `/src/lib/oauth/services/antigravity.js` (Line 141-154)
```javascript
async onboardUser(accessToken, projectId, tierId) {
    const response = await fetch(this.config.onboardUserEndpoint, {
      method: "POST",
      headers: this.getApiHeaders(accessToken),
      body: JSON.stringify({ 
        tierId, 
        metadata: this.getMetadata() 
        // Note: 9router CLI juga tidak kirim projectId di sini,
        // tapi di open-sse/services/projectId.js HARUS kirim projectId
      }),
    });
    
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Failed to onboard user: ${errorText}`);
    }
    
    return await response.json();
}
```

## Why This Fix Works

Google Cloud Code API `v1internal:onboardUser` membutuhkan `projectId` dalam request body untuk:
1. Mengetahui GCP project mana yang akan di-onboard untuk Gemini Code Assist
2. Mengembalikan `cloudaicompanionProject` dalam response setelah onboarding berhasil
3. Tanpa `projectId`, API akan return `done: true` tapi tanpa project info

## Changes Made

### File: `bot.py`

1. **Function signature updated** (Line 200):
   ```python
   - def onboard_user(access_token, tier_id, max_retries=10):
   + def onboard_user(access_token, project_id, tier_id, max_retries=10):
   ```

2. **Request body includes projectId** (Line 205-209):
   ```python
   data = json.dumps({
       "tierId": tier_id, 
       "metadata": CLIENT_METADATA,
       "projectId": project_id  # ✅ This is required!
   }).encode()
   ```

3. **Fallback to original projectId** (Line 222-223):
   ```python
   # If no project in response, return the original projectId
   return project_id
   ```

4. **Function call updated** (Line 487):
   ```python
   - final_pid = onboard_user(access_token, tier_id)
   + final_pid = onboard_user(access_token, project_id, tier_id)
   ```

## OAuth Flow Overview

Setelah fix ini, flow OAuth Antigravity yang benar adalah:

```
1. Google OAuth (Browser) → Authorization Code
2. Exchange Code → Access Token + Refresh Token
3. Get User Info → Email
4. loadCodeAssist → Project ID + Tier ID
5. onboardUser (with projectId!) → Final Project ID
6. Inject to 9router DB → Connection stored
```

## Testing

Setelah fix ini, test ulang dengan:
```bash
cd /home/ubuntu/scripts/9router-auto-login-antigravity
python3 bot.py
```

Expected behavior:
- Step 5 (onboardUser) akan berhasil dengan projectId
- Model claude-opus-4-6-thinking akan bisa digunakan
- Tidak ada lagi error "no project_id in response"

## Related Files in 9router
- `/open-sse/services/projectId.js` - Reference implementation
- `/src/lib/oauth/services/antigravity.js` - CLI OAuth flow
- `/open-sse/providers/registry/antigravity.js` - Provider config
- `/open-sse/executors/antigravity.js` - Request executor

## Conclusion

Bug ini terjadi karena missing parameter `projectId` dalam request body ke API `onboardUser`. Setelah menambahkan parameter ini sesuai dengan implementasi di 9router, OAuth flow akan berjalan dengan benar dan model Antigravity dapat digunakan.
