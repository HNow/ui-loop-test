import subprocess
import json

# Render
print("Rendering preview...")
result = subprocess.run(
    ["uv", "run", "--with-requirements", "agent/requirements.txt", 
     "python", "-m", "agent.tools", "render", "http://127.0.0.1:56007/preview.html"],
    capture_output=True, text=True
)
data = json.loads(result.stdout)
screenshot = data['screenshot']
print(f"Screenshot captured: {len(screenshot)} chars")

# Diff against reference - pass base64 via stdin
print("Comparing to reference...")
result2 = subprocess.run(
    ["uv", "run", "--with-requirements", "agent/requirements.txt",
     "python", "-m", "agent.tools", "diff", 
     "static/components/comp_1774698443_3081/reference.jpg",
     "-"],  # - means read from stdin
    input=screenshot,
    capture_output=True, text=True
)
diff_data = json.loads(result2.stdout)
ssim = diff_data.get('ssim', 0)
print(f"SSIM: {ssim}")

# Save iteration
print("Saving iteration...")
save_data = json.dumps({"screenshot": screenshot, "ssim": ssim})
result3 = subprocess.run(
    ["uv", "run", "--with-requirements", "agent/requirements.txt",
     "python", "-m", "agent.tools", "save", "comp_1774698443_3081"],
    input=save_data, capture_output=True, text=True
)
print(result3.stdout)
print(f"\n✅ Iteration 1 complete - SSIM: {ssim:.4f}")
