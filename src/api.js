let token = "";
export async function api(path, method = "GET", body) {
  const response = await fetch("/api" + path, {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-SportsCards-Token": token,
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "The request failed.");
  if (result.token) token = result.token;
  return result;
}
export function upload(file, progress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/photos");
    xhr.setRequestHeader("X-SportsCards-Token", token);
    xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name));
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) =>
      progress(e.lengthComputable ? Math.round((100 * e.loaded) / e.total) : 0);
    xhr.timeout = 90000;
    xhr.onerror = () =>
      reject(new Error("Upload interrupted. Retry this photo."));
    xhr.ontimeout = () =>
      reject(new Error("Upload timed out. Retry this photo."));
    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText);
        xhr.status < 300 ? resolve(data) : reject(new Error(data.error));
      } catch {
        reject(new Error("The server response was unreadable."));
      }
    };
    xhr.send(file);
  });
}
export const money = (cents) =>
  cents == null
    ? "Not estimated"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
      }).format(cents / 100);
export const cents = (value) => Math.round(Number(value) * 100);
export const fields = [
  "player",
  "year",
  "set",
  "number",
  "variant",
  "grade",
  "condition",
];
export const labels = {
  player: "Player",
  year: "Year",
  set: "Set",
  number: "Card number",
  variant: "Variant",
  grade: "Grade",
  condition: "Condition",
};
