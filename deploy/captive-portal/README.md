# Captive Portal for WiFiDrop

WiFiDrop can answer the standard HTTP connectivity probes used by Android/ChromeOS,
Apple devices and Windows. This is only the web-server half of a captive portal.

For a phone to show a system "Sign in to network" / "Open network page" notification,
the Wi-Fi network itself must direct connectivity-check hostnames to the WiFiDrop
server (normally through DNS supplied by DHCP) or advertise a Captive Portal API URI
(DHCP option 114 / RFC 8910). An application running on an ordinary PC behind an
unmodified home router cannot force this behavior on other clients.

## Recommended topology

Use a dedicated WiFiDrop hotspot / router where you control DHCP and DNS:

1. Give the WiFiDrop server a stable LAN address, e.g. `192.168.4.1`.
2. Set `CAPTIVE_PORTAL_ENABLED=true` and keep `CAPTIVE_PORTAL_PORT=80`.
3. Make DHCP hand clients the controlled DNS server.
4. Configure that DNS server using `dnsmasq-wifidrop.conf.example`, replacing the IP.
5. Allow TCP 80 and the main WiFiDrop port through the private-network firewall.
6. Restart Wi-Fi on the client and reconnect.

The DNS overrides intentionally cover only known connectivity-check hosts. Do not use
a wildcard rule that redirects every domain: it breaks normal browsing and HTTPS.

## Platform notes

- Android/ChromeOS commonly checks `/generate_204` over HTTP (and may also perform
  HTTPS validation). WiFiDrop redirects the HTTP probe to the upload page.
- iOS/iPadOS/macOS commonly checks Apple's captive portal endpoints. WiFiDrop redirects
  those HTTP probes without returning Apple's normal success marker.
- Windows checks Microsoft NCSI endpoints; WiFiDrop redirects the HTTP text probes.
- OS vendors change probe behavior. No implementation can guarantee the system popup
  on every OS/version, especially when the device uses encrypted/private DNS, VPN,
  cellular-assisted validation, or HTTPS-only checks.

## Ordinary home/office Wi-Fi

If the WiFiDrop PC does not control the router/DHCP/DNS, leave
`CAPTIVE_PORTAL_ENABLED=false`. The project continues to work normally by IP. A local
DNS name/bookmark/PWA can reduce manual typing, but cannot create the OS captive-portal
notification by itself.

## Автономная точка доступа Windows

Для сценария без настройки роутера добавлен `run_hotspot.bat`. Он запускается с правами
администратора и пытается создать отдельную Wi-Fi сеть средствами Windows Hosted Network.
В этом режиме WiFiDrop сам:

- создаёт SSID и пароль из `.env`;
- назначает компьютеру адрес `HOTSPOT_GATEWAY_IP` (по умолчанию `192.168.50.1`);
- раздаёт адреса клиентам через встроенный DHCP;
- объявляет компьютер DNS-сервером и направляет captive-проверки на WiFiDrop;
- публикует DHCP option 114 (Captive Portal API);
- слушает HTTP-проверки ОС на TCP/80 и переводит их на интерфейс WiFiDrop.

Настройки:

```env
HOTSPOT_ENABLED=false
HOTSPOT_SSID=WiFiDrop
HOTSPOT_PASSWORD=WiFiDrop2026
HOTSPOT_GATEWAY_IP=192.168.50.1
```

Обычный запуск `run.bat` не включает точку доступа. Для автономной сети используйте
`run_hotspot.bat`; он сам запросит повышение прав через UAC и временно включает
`HOTSPOT_ENABLED=true` только для текущего процесса.

### Ограничение современных Wi-Fi адаптеров Windows

Полноценный режим требует, чтобы драйвер Wi-Fi поддерживал Windows Hosted Network.
Microsoft постепенно заменила этот старый механизм на Mobile Hotspot/Wi-Fi Direct. Новый
Mobile Hotspot можно запустить программно, но штатный API не предоставляет приложению
нужного контроля над DHCP/DNS для гарантированной captive-portal сети. Поэтому WiFiDrop
не делает вид, что такой режим работает: если Hosted Network не поддерживается, запуск
автономного Captive Portal останавливается и открывает системную страницу Mobile Hotspot.

Проверить поддержку вручную можно командой от администратора:

```bat
netsh wlan set hostednetwork mode=allow
```

Если драйвер отвергает Hosted Network, для гарантированного системного уведомления нужен
Wi-Fi адаптер/драйвер с поддержкой Hosted Network либо отдельная точка доступа/OpenWrt,
где WiFiDrop может контролировать DHCP/DNS.
