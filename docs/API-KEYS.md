# API Keys Setup Guide

All enrichment API keys are optional. Meli works fully without them — you only lose the external reputation scores. GeoLite2 geolocation is always available with a free MaxMind account (no per-query costs).

## MaxMind GeoLite2 (Geolocation — Strongly Recommended)

**Cost:** Free (requires free account)  
**Limit:** No per-query limit — runs offline from local mmdb files  
**What it provides:** Country, city, coordinates, ASN, ISP

1. Create account at https://www.maxmind.com/en/geolite2/signup
2. Log in → Account → Manage License Keys → Generate new license key
3. In Meli → Settings → Enrichment APIs → MaxMind License Key → paste key
4. Click "Download GeoLite2 Databases Now"
5. Databases download to `~/.local/share/meli/geoip/`

The databases are approximately 60–70 MB total. Refresh them monthly for accuracy (MaxMind updates weekly).

---

## AbuseIPDB

**Cost:** Free tier  
**Limit:** 1,000 checks/day  
**What it provides:** Abuse confidence score (0–100%), number of reports, ISP, Tor exit status, last report date

1. Register at https://www.abuseipdb.com/register
2. Account → API → Create Key
3. In Meli → Settings → Enrichment APIs → AbuseIPDB API Key

**Interpretation:**
- 0–24%: Low confidence of abuse
- 25–74%: Medium confidence
- 75–100%: High confidence — definitely known attacker

---

## GreyNoise

**Cost:** Free community API  
**Limit:** 1,000 checks/day (community)  
**What it provides:** Classification (benign/malicious/unknown), noise tag, last seen date

1. Sign up at https://www.greynoise.io/
2. Account → API Access → Copy API key
3. In Meli → Settings → Enrichment APIs → GreyNoise API Key

**Interpretation:**
- `noise: true` — scanning the whole internet (mass scanner, Shodan, etc.)
- `classification: malicious` — known threat actor
- `classification: benign` — legitimate service (Google, AWS, etc.)

GreyNoise is particularly useful for filtering out "background noise" scanners from real targeted attacks.

---

## VirusTotal

**Cost:** Free public API  
**Limit:** 500 lookups/day, 4 per minute  
**What it provides:** IP reputation (malicious/suspicious votes from 70+ security vendors), file hash malware scan

1. Register at https://www.virustotal.com/
2. Profile → API Key → Copy
3. In Meli → Settings → Enrichment APIs → VirusTotal API Key

Meli uses VirusTotal for both:
- **IP lookups** — shown in Attackers view and IP Reputation view
- **File hash lookups** — shown in Payloads view for captured malware

---

## Shodan

**Cost:** Free membership gives limited access  
**Limit:** 100 query credits/month (free tier)  
**What it provides:** Open ports, service banners, known vulnerabilities (CVEs), hostnames, operating system

1. Create account at https://www.shodan.io/
2. Account → Overview → API Key
3. In Meli → Settings → Enrichment APIs → Shodan API Key

Shodan has strict rate limits on the free tier. Meli caches results aggressively (24h TTL by default) to minimize API usage.

---

## IPInfo

**Cost:** Free tier  
**Limit:** 50,000 lookups/month  
**What it provides:** ASN, organization, hostname, country/city/region, VPN/proxy/Tor/relay detection

1. Sign up at https://ipinfo.io/signup
2. Dashboard → Access Token → Copy
3. In Meli → Settings → Enrichment APIs → IPInfo API Key

IPInfo's privacy detection (VPN/proxy/Tor) requires a paid plan. The free token gives all other fields.

---

## Security

API keys entered in the Settings UI are stored encrypted in the SQLite database using Fernet (AES-128-CBC) with a key derived from your master password via Argon2id. They are never stored in plaintext in the config file.

Keys are decrypted in memory only when needed for API calls and are never logged.
