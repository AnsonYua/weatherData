import { list, put } from "@vercel/blob";

const DEFAULT_CACHE_TTL_MS = 15_000;
const jsonCache = new Map();

function clone(value) {
  return value == null ? value : structuredClone(value);
}

function getFreshCacheEntry(path, ttlMs) {
  const entry = jsonCache.get(path);
  if (!entry) return null;
  if (Date.now() > entry.expiresAt) {
    jsonCache.delete(path);
    return null;
  }
  return entry;
}

async function resolveBlobUrl(path) {
  const result = await list({ prefix: path, limit: 1 });
  const blob = result.blobs.find((item) => item.pathname === path);
  return blob?.url || null;
}

export async function readBlobJson(path, fallback, options = {}) {
  const {
    bypassCache = false,
    cacheTtlMs = DEFAULT_CACHE_TTL_MS
  } = options;

  if (!bypassCache) {
    const cached = getFreshCacheEntry(path, cacheTtlMs);
    if (cached) {
      const data = await cached.valuePromise;
      return clone(data);
    }
  }

  const valuePromise = (async () => {
    const url = await resolveBlobUrl(path);
    if (!url) return clone(fallback);

    const cacheBustedUrl = `${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`;
    const response = await fetch(cacheBustedUrl, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Blob read failed for ${path}: HTTP ${response.status}`);
    }

    return clone(await response.json());
  })();

  jsonCache.set(path, {
    expiresAt: Date.now() + cacheTtlMs,
    valuePromise
  });

  try {
    const data = await valuePromise;
    return clone(data);
  } catch (error) {
    jsonCache.delete(path);
    throw error;
  }
}

export async function writeBlobJson(path, payload) {
  const blob = await put(path, JSON.stringify(payload, null, 2), {
    access: "public",
    contentType: "application/json",
    addRandomSuffix: false,
    allowOverwrite: true
  });

  jsonCache.set(path, {
    expiresAt: Date.now() + DEFAULT_CACHE_TTL_MS,
    valuePromise: Promise.resolve(clone(payload))
  });

  return blob;
}

export function clearBlobJsonCache(path) {
  jsonCache.delete(path);
}
