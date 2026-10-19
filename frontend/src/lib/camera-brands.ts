/**
 * Camera-brand connection cheat sheets.
 *
 * The single biggest snag for new users is "what's my camera's stream
 * URL and where do I turn on RTSP/ONVIF?" These entries answer that per
 * brand. Each carries one or more RTSP URL templates and the exact
 * clicks to enable RTSP/ONVIF + find credentials.
 *
 * Templates use <user> <pass> <ip> placeholders. The help panel can
 * drop a template straight into the stream-URL field; the user swaps the
 * three placeholders. Credentials may instead be left out of the URL and
 * entered in Nurby's Credentials section.
 *
 * Locale strategy (#265): steps, notes, and template labels are data, so
 * they carry their translations inline as LocalizedText instead of living
 * in the UI catalog. English is the source; helpers fall back to it per
 * string. Menu paths (Configuration → Network → …), tool names, URL
 * fragments, and protocol tokens stay as written because the camera's
 * own UI and the wire format are English regardless of app locale.
 *
 * support:
 *   "yes"     RTSP works out of the box or after a setting toggle
 *   "limited" only some models / requires extra firmware or an add-on
 *   "no"      cloud-locked. No direct RTSP without a bridge
 */

export type RtspSupport = "yes" | "limited" | "no";

/** A piece of brand data served per locale; English is the source. */
export interface LocalizedText {
  en: string;
  es?: string;
}

export interface RtspTemplate {
  label: LocalizedText; // e.g. "Main stream" / "Flujo principal"
  url: string; // contains <user> <pass> <ip>
}

export interface CameraBrand {
  id: string;
  name: string;
  support: RtspSupport;
  /** Default RTSP port, shown as a hint. */
  port?: number;
  templates: RtspTemplate[];
  /** Ordered, plain-English steps to get the connection details. */
  steps: LocalizedText[];
  /** Gotchas worth calling out. */
  notes?: LocalizedText[];
}

export const CAMERA_BRANDS: CameraBrand[] = [
  {
    id: "hikvision",
    name: "Hikvision",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Main stream", es: "Flujo principal" }, url: "rtsp://<user>:<pass>@<ip>:554/Streaming/Channels/101" },
      { label: { en: "Sub stream", es: "Flujo secundario" }, url: "rtsp://<user>:<pass>@<ip>:554/Streaming/Channels/102" },
    ],
    steps: [
      {
        en: "Find the camera's IP. check your router's device list, or use the Hikvision SADP tool.",
        es: "Encuentra la IP de la cámara: revisa la lista de dispositivos de tu router o usa la herramienta SADP de Hikvision.",
      },
      {
        en: "Log into the camera's web page at http://<ip> with your admin account.",
        es: "Entra en la página web de la cámara en http://<ip> con tu cuenta de administrador.",
      },
      {
        en: "Go to Configuration → Network → Advanced Settings → Integration Protocol and tick Enable ONVIF, then add an ONVIF user.",
        es: "Ve a Configuration → Network → Advanced Settings → Integration Protocol, marca Enable ONVIF y añade un usuario ONVIF.",
      },
      {
        en: "RTSP is on by default on port 554. Use your admin username and password.",
        es: "RTSP está activo por defecto en el puerto 554. Usa tu usuario y contraseña de administrador.",
      },
    ],
    notes: [
      {
        en: "Channel 101 = main (full quality), 102 = sub (lighter). Start with the sub stream on a weak machine.",
        es: "El canal 101 es el principal (calidad completa) y el 102 el secundario (más ligero). Empieza por el secundario en un equipo modesto.",
      },
    ],
  },
  {
    id: "dahua",
    name: "Dahua",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Main stream", es: "Flujo principal" }, url: "rtsp://<user>:<pass>@<ip>:554/cam/realmonitor?channel=1&subtype=0" },
      { label: { en: "Sub stream", es: "Flujo secundario" }, url: "rtsp://<user>:<pass>@<ip>:554/cam/realmonitor?channel=1&subtype=1" },
    ],
    steps: [
      {
        en: "Find the camera's IP (router device list, or the Dahua ConfigTool).",
        es: "Encuentra la IP de la cámara (lista de dispositivos del router o la herramienta Dahua ConfigTool).",
      },
      {
        en: "Log into http://<ip> with your admin account.",
        es: "Entra en http://<ip> con tu cuenta de administrador.",
      },
      {
        en: "Go to Setting → Network → Port and confirm RTSP port 554; enable ONVIF under Setting → Network → Platform Access if present.",
        es: "Ve a Setting → Network → Port y confirma el puerto RTSP 554; activa ONVIF en Setting → Network → Platform Access si aparece.",
      },
      {
        en: "Use your admin username and password.",
        es: "Usa tu usuario y contraseña de administrador.",
      },
    ],
    notes: [
      {
        en: "subtype=0 is the main stream, subtype=1 the sub stream.",
        es: "subtype=0 es el flujo principal y subtype=1 el secundario.",
      },
    ],
  },
  {
    id: "reolink",
    name: "Reolink",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Main stream", es: "Flujo principal" }, url: "rtsp://<user>:<pass>@<ip>:554/h264Preview_01_main" },
      { label: { en: "Sub stream", es: "Flujo secundario" }, url: "rtsp://<user>:<pass>@<ip>:554/h264Preview_01_sub" },
    ],
    steps: [
      {
        en: "Open the Reolink app or client and find the camera's IP under Device Settings → Network → Network Information.",
        es: "Abre la app o el cliente de Reolink y encuentra la IP de la cámara en Device Settings → Network → Network Information.",
      },
      {
        en: "Go to Device Settings → Network → Advanced → Port Settings and enable RTSP and ONVIF.",
        es: "Ve a Device Settings → Network → Advanced → Port Settings y activa RTSP y ONVIF.",
      },
      {
        en: "Use the camera's own username and password (not your Reolink cloud login).",
        es: "Usa el usuario y la contraseña de la propia cámara (no los de tu cuenta en la nube de Reolink).",
      },
    ],
    notes: [
      {
        en: "Battery-powered Reolink models (Argus, etc) often do NOT support RTSP. wired/PoE models do.",
        es: "Los modelos Reolink con batería (Argus, etc.) suelen NO ser compatibles con RTSP; los cableados/PoE sí.",
      },
    ],
  },
  {
    id: "amcrest",
    name: "Amcrest",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Main stream", es: "Flujo principal" }, url: "rtsp://<user>:<pass>@<ip>:554/cam/realmonitor?channel=1&subtype=0" },
      { label: { en: "Sub stream", es: "Flujo secundario" }, url: "rtsp://<user>:<pass>@<ip>:554/cam/realmonitor?channel=1&subtype=1" },
    ],
    steps: [
      {
        en: "Find the camera's IP (router list, or the Amcrest IP Config tool).",
        es: "Encuentra la IP de la cámara (lista del router o la herramienta Amcrest IP Config).",
      },
      {
        en: "Log into http://<ip> with your admin account.",
        es: "Entra en http://<ip> con tu cuenta de administrador.",
      },
      {
        en: "Setup → Network → Connection. Confirm RTSP port 554. ONVIF is usually on by default.",
        es: "Setup → Network → Connection. Confirma el puerto RTSP 554. ONVIF suele venir activado por defecto.",
      },
      {
        en: "Use your admin username and password.",
        es: "Usa tu usuario y contraseña de administrador.",
      },
    ],
    notes: [
      {
        en: "Amcrest shares Dahua's URL scheme.",
        es: "Amcrest comparte el esquema de URL de Dahua.",
      },
    ],
  },
  {
    id: "tapo",
    name: "TP-Link Tapo",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "HD stream", es: "Flujo HD" }, url: "rtsp://<user>:<pass>@<ip>:554/stream1" },
      { label: { en: "SD stream", es: "Flujo SD" }, url: "rtsp://<user>:<pass>@<ip>:554/stream2" },
    ],
    steps: [
      {
        en: "In the Tapo app, open the camera → Settings → Advanced Settings → Camera Account.",
        es: "En la app Tapo, abre la cámara → Settings → Advanced Settings → Camera Account.",
      },
      {
        en: "Create a Camera Account username + password here. THIS is what the RTSP URL uses, not your TP-Link cloud login.",
        es: "Crea aquí un usuario y una contraseña de Camera Account. Eso es lo que usa la URL RTSP, no tu cuenta en la nube de TP-Link.",
      },
      {
        en: "Find the camera IP under Settings → Device Info, or in your router.",
        es: "Encuentra la IP de la cámara en Settings → Device Info o en tu router.",
      },
      {
        en: "Use the Camera Account username and password you just made.",
        es: "Usa el usuario y la contraseña de Camera Account que acabas de crear.",
      },
    ],
    notes: [
      {
        en: "The most common Tapo mistake. Using the TP-Link app login instead of the separate Camera Account.",
        es: "El error más común con Tapo: usar la cuenta de la app de TP-Link en lugar de la Camera Account independiente.",
      },
    ],
  },
  {
    id: "wyze",
    name: "Wyze",
    support: "limited",
    port: 8554,
    templates: [
      { label: { en: "RTSP firmware", es: "Firmware RTSP" }, url: "rtsp://<user>:<pass>@<ip>:8554/live" },
    ],
    steps: [
      {
        en: "Wyze cameras only do RTSP after flashing the official RTSP firmware (Wyze Cam v2 / v3 / Pan).",
        es: "Las cámaras Wyze solo ofrecen RTSP tras instalar el firmware oficial RTSP (Wyze Cam v2 / v3 / Pan).",
      },
      {
        en: "In the Wyze app, open the camera → Settings → Advanced Settings → RTSP, enable it, and set a username + password.",
        es: "En la app Wyze, abre la cámara → Settings → Advanced Settings → RTSP, actívalo y define un usuario y una contraseña.",
      },
      {
        en: "The app shows the full rtsp:// URL. copy it here.",
        es: "La app muestra la URL rtsp:// completa; cópiala aquí.",
      },
    ],
    notes: [
      {
        en: "Stock Wyze firmware has no RTSP. if you don't see the RTSP option, flash the RTSP firmware from Wyze's support site first.",
        es: "El firmware original de Wyze no incluye RTSP. Si no ves la opción RTSP, instala primero el firmware RTSP del sitio de soporte de Wyze.",
      },
    ],
  },
  {
    id: "unifi",
    name: "Ubiquiti UniFi Protect",
    support: "yes",
    port: 7447,
    templates: [
      { label: { en: "RTSP(S) stream", es: "Flujo RTSP(S)" }, url: "rtsps://<ip>:7441/<streamId>?enableSrtp" },
    ],
    steps: [
      {
        en: "Open UniFi Protect → pick the camera → Settings → Advanced → RTSP.",
        es: "Abre UniFi Protect → elige la cámara → Settings → Advanced → RTSP.",
      },
      {
        en: "Toggle on one of the quality streams (High / Medium / Low). Protect generates a full rtsps:// URL.",
        es: "Activa uno de los flujos de calidad (High / Medium / Low). Protect genera una URL rtsps:// completa.",
      },
      {
        en: "Copy that exact URL here. It already includes the stream id and port.",
        es: "Copia esa URL exacta aquí. Ya incluye el identificador de flujo y el puerto.",
      },
    ],
    notes: [
      {
        en: "UniFi uses RTSPS (TLS) on port 7441. credentials are embedded in the generated URL, so the Credentials section can stay empty.",
        es: "UniFi usa RTSPS (TLS) en el puerto 7441; las credenciales van incluidas en la URL generada, así que la sección de credenciales puede quedar vacía.",
      },
    ],
  },
  {
    id: "axis",
    name: "Axis",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Main stream", es: "Flujo principal" }, url: "rtsp://<user>:<pass>@<ip>/axis-media/media.amp" },
    ],
    steps: [
      {
        en: "Find the camera IP (router list, or the AXIS IP Utility).",
        es: "Encuentra la IP de la cámara (lista del router o AXIS IP Utility).",
      },
      {
        en: "Log into http://<ip> with your admin account.",
        es: "Entra en http://<ip> con tu cuenta de administrador.",
      },
      {
        en: "RTSP and ONVIF are supported by default. Add an ONVIF user under System → ONVIF if you want a separate account.",
        es: "RTSP y ONVIF vienen soportados por defecto. Añade un usuario ONVIF en System → ONVIF si quieres una cuenta aparte.",
      },
    ],
  },
  {
    id: "foscam",
    name: "Foscam",
    support: "yes",
    port: 88,
    templates: [
      { label: { en: "Main stream", es: "Flujo principal" }, url: "rtsp://<user>:<pass>@<ip>:88/videoMain" },
      { label: { en: "Sub stream", es: "Flujo secundario" }, url: "rtsp://<user>:<pass>@<ip>:88/videoSub" },
    ],
    steps: [
      {
        en: "Find the camera IP in the Foscam app under Settings → Device Info, or in your router.",
        es: "Encuentra la IP de la cámara en la app Foscam, en Settings → Device Info, o en tu router.",
      },
      {
        en: "Log into the web UI and enable RTSP/ONVIF under Settings → Network → Port if not already on.",
        es: "Entra en la interfaz web y activa RTSP/ONVIF en Settings → Network → Port si no lo está ya.",
      },
      {
        en: "Foscam often uses port 88, sometimes 554. check the Port settings page.",
        es: "Foscam suele usar el puerto 88, a veces el 554. Revisa la página de ajustes de puertos.",
      },
    ],
    notes: [
      {
        en: "Port varies by model. If 88 fails, try 554.",
        es: "El puerto varía según el modelo. Si el 88 falla, prueba el 554.",
      },
    ],
  },
  {
    id: "lorex",
    name: "Lorex",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Main stream", es: "Flujo principal" }, url: "rtsp://<user>:<pass>@<ip>:554/cam/realmonitor?channel=1&subtype=0" },
      { label: { en: "Sub stream", es: "Flujo secundario" }, url: "rtsp://<user>:<pass>@<ip>:554/cam/realmonitor?channel=1&subtype=1" },
    ],
    steps: [
      {
        en: "Find the camera/NVR IP in the Lorex app or on the NVR's network screen.",
        es: "Encuentra la IP de la cámara o del NVR en la app Lorex o en la pantalla de red del NVR.",
      },
      {
        en: "Enable RTSP/ONVIF in the NVR or camera Network settings.",
        es: "Activa RTSP/ONVIF en los ajustes de red del NVR o de la cámara.",
      },
      {
        en: "Use the device's admin username and password. For an NVR, change channel=1 to the channel you want.",
        es: "Usa el usuario y la contraseña de administrador del dispositivo. En un NVR, cambia channel=1 por el canal que quieras.",
      },
    ],
    notes: [
      {
        en: "Lorex is Dahua-based, so it uses the Dahua URL scheme.",
        es: "Lorex se basa en Dahua, así que usa el esquema de URL de Dahua.",
      },
    ],
  },
  {
    id: "annke",
    name: "Annke",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Hikvision-style", es: "Estilo Hikvision" }, url: "rtsp://<user>:<pass>@<ip>:554/Streaming/Channels/101" },
      { label: { en: "Dahua-style", es: "Estilo Dahua" }, url: "rtsp://<user>:<pass>@<ip>:554/cam/realmonitor?channel=1&subtype=0" },
    ],
    steps: [
      {
        en: "Find the camera IP (router list).",
        es: "Encuentra la IP de la cámara (lista del router).",
      },
      {
        en: "Log into the web UI and enable ONVIF under Network → Advanced.",
        es: "Entra en la interfaz web y activa ONVIF en Network → Advanced.",
      },
      {
        en: "Annke uses either the Hikvision or Dahua URL scheme depending on the model. Try the Hikvision one first.",
        es: "Annke usa el esquema de URL de Hikvision o de Dahua según el modelo. Prueba primero el de Hikvision.",
      },
    ],
    notes: [
      {
        en: "If the Hikvision-style URL fails, the camera is Dahua-based, so use the second template.",
        es: "Si la URL estilo Hikvision falla, la cámara es Dahua: usa la segunda plantilla.",
      },
    ],
  },
  {
    id: "uniview",
    name: "Uniview (UNV)",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Main stream", es: "Flujo principal" }, url: "rtsp://<user>:<pass>@<ip>:554/unicast/c1/s0/live" },
      { label: { en: "Sub stream", es: "Flujo secundario" }, url: "rtsp://<user>:<pass>@<ip>:554/unicast/c1/s1/live" },
    ],
    steps: [
      {
        en: "Find the camera IP (router list, or Uniview's EZTools / Guard tool).",
        es: "Encuentra la IP de la cámara (lista del router o las herramientas EZTools / Guard de Uniview).",
      },
      {
        en: "Log into http://<ip> with your admin account.",
        es: "Entra en http://<ip> con tu cuenta de administrador.",
      },
      {
        en: "Setup → Network → Port. Confirm RTSP 554. ONVIF is on by default; add an ONVIF user under Network → Platform if you want a separate login.",
        es: "Setup → Network → Port. Confirma RTSP 554. ONVIF viene activado; añade un usuario ONVIF en Network → Platform si quieres un acceso aparte.",
      },
      {
        en: "Use your admin username and password. For an NVR, change c1 to the channel number.",
        es: "Usa tu usuario y contraseña de administrador. En un NVR, cambia c1 por el número de canal.",
      },
    ],
    notes: [
      {
        en: "c1 = channel 1, s0 = main / s1 = sub.",
        es: "c1 = canal 1; s0 = principal / s1 = secundario.",
      },
    ],
  },
  {
    id: "hanwha",
    name: "Hanwha Vision / Wisenet (Samsung)",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Main (profile1)", es: "Principal (profile1)" }, url: "rtsp://<user>:<pass>@<ip>:554/profile1/media.smp" },
      { label: { en: "Sub (profile2)", es: "Secundario (profile2)" }, url: "rtsp://<user>:<pass>@<ip>:554/profile2/media.smp" },
    ],
    steps: [
      {
        en: "Find the camera IP (router list, or the Wisenet Device Manager).",
        es: "Encuentra la IP de la cámara (lista del router o Wisenet Device Manager).",
      },
      {
        en: "Log into http://<ip> with your admin account.",
        es: "Entra en http://<ip> con tu cuenta de administrador.",
      },
      {
        en: "Setup → Network → ONVIF. add an ONVIF user. RTSP is enabled by default on 554.",
        es: "Setup → Network → ONVIF: añade un usuario ONVIF. RTSP viene activado en el 554.",
      },
      {
        en: "Use your admin username and password.",
        es: "Usa tu usuario y contraseña de administrador.",
      },
    ],
    notes: [
      {
        en: "Profile names can differ per model. If profile1/2 fail, check Setup → Video profiles for the exact profile name.",
        es: "Los nombres de perfil pueden variar según el modelo. Si profile1/2 fallan, consulta Setup → Video profiles para el nombre exacto.",
      },
    ],
  },
  {
    id: "bosch",
    name: "Bosch",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Stream 1", es: "Flujo 1" }, url: "rtsp://<user>:<pass>@<ip>:554/?inst=1" },
      { label: { en: "Stream 2", es: "Flujo 2" }, url: "rtsp://<user>:<pass>@<ip>:554/?inst=2" },
    ],
    steps: [
      {
        en: "Easiest path. Use the Scan tab above. Bosch cameras are ONVIF-compliant and discover cleanly.",
        es: "El camino más fácil: usa la pestaña de escaneo de arriba. Las cámaras Bosch cumplen ONVIF y se detectan sin problema.",
      },
      {
        en: "Otherwise log into http://<ip>, go to Configuration → Network → Network Access, and confirm the RTSP port.",
        es: "Si no, entra en http://<ip>, ve a Configuration → Network → Network Access y confirma el puerto RTSP.",
      },
      {
        en: "Use your camera's service/admin account.",
        es: "Usa la cuenta de servicio o de administrador de la cámara.",
      },
    ],
    notes: [
      {
        en: "Bosch RTSP paths vary by firmware. If the templates fail, the Scan tab + ONVIF is the reliable route.",
        es: "Las rutas RTSP de Bosch varían según el firmware. Si las plantillas fallan, lo fiable es el escaneo + ONVIF.",
      },
    ],
  },
  {
    id: "vivotek",
    name: "Vivotek",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Stream 1", es: "Flujo 1" }, url: "rtsp://<user>:<pass>@<ip>:554/live.sdp" },
      { label: { en: "Stream 2", es: "Flujo 2" }, url: "rtsp://<user>:<pass>@<ip>:554/live2.sdp" },
    ],
    steps: [
      {
        en: "Find the camera IP (router list, or Vivotek's Shepherd / IW2 tool).",
        es: "Encuentra la IP de la cámara (lista del router o las herramientas Shepherd / IW2 de Vivotek).",
      },
      {
        en: "Log into http://<ip> with your admin account.",
        es: "Entra en http://<ip> con tu cuenta de administrador.",
      },
      {
        en: "Configuration → Network → General confirms RTSP 554; enable ONVIF under Security → ONVIF.",
        es: "En Configuration → Network → General confirma RTSP 554; activa ONVIF en Security → ONVIF.",
      },
      {
        en: "Use your admin username and password.",
        es: "Usa tu usuario y contraseña de administrador.",
      },
    ],
    notes: [
      {
        en: "Stream path can be live.sdp, live1s1.sdp, or live2.sdp depending on model.",
        es: "La ruta del flujo puede ser live.sdp, live1s1.sdp o live2.sdp según el modelo.",
      },
    ],
  },
  {
    id: "honeywell",
    name: "Honeywell",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Main stream", es: "Flujo principal" }, url: "rtsp://<user>:<pass>@<ip>:554/h264" },
      { label: { en: "Channel/stream", es: "Canal/flujo" }, url: "rtsp://<user>:<pass>@<ip>:554/ch01/0" },
    ],
    steps: [
      {
        en: "Use the Scan tab above first. Most Honeywell IP cameras are ONVIF-compliant.",
        es: "Prueba primero la pestaña de escaneo de arriba. La mayoría de las cámaras IP de Honeywell cumplen ONVIF.",
      },
      {
        en: "Otherwise log into http://<ip>, confirm the RTSP port under Network settings, and enable ONVIF if present.",
        es: "Si no, entra en http://<ip>, confirma el puerto RTSP en los ajustes de red y activa ONVIF si está disponible.",
      },
      {
        en: "Use your admin username and password.",
        es: "Usa tu usuario y contraseña de administrador.",
      },
    ],
    notes: [
      {
        en: "Honeywell spans many series (Performance, Equip, 30/35 Series) with different paths. ONVIF/Scan is the safe bet.",
        es: "Honeywell abarca muchas series (Performance, Equip, 30/35) con rutas distintas. ONVIF o el escaneo es la apuesta segura.",
      },
    ],
  },
  {
    id: "avigilon",
    name: "Avigilon (Motorola)",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Primary", es: "Principal" }, url: "rtsp://<user>:<pass>@<ip>:554/defaultPrimary?streamType=u" },
      { label: { en: "Secondary", es: "Secundario" }, url: "rtsp://<user>:<pass>@<ip>:554/defaultSecondary?streamType=u" },
    ],
    steps: [
      {
        en: "Find the camera IP (router list, or the Avigilon Camera Configuration Tool).",
        es: "Encuentra la IP de la cámara (lista del router o Avigilon Camera Configuration Tool).",
      },
      {
        en: "Log into the camera web UI and confirm RTSP/ONVIF are enabled.",
        es: "Entra en la interfaz web de la cámara y confirma que RTSP/ONVIF están activados.",
      },
      {
        en: "Use the camera's admin account. StreamType=u requests UDP.",
        es: "Usa la cuenta de administrador de la cámara. StreamType=u pide UDP.",
      },
    ],
  },
  {
    id: "ipro",
    name: "Panasonic / i-PRO",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Stream 1", es: "Flujo 1" }, url: "rtsp://<user>:<pass>@<ip>:554/MediaInput/h264/stream_1" },
      { label: { en: "Stream 2", es: "Flujo 2" }, url: "rtsp://<user>:<pass>@<ip>:554/MediaInput/h264/stream_2" },
    ],
    steps: [
      {
        en: "Find the camera IP (router list, or the i-PRO Configuration Tool / Easy IP Setup).",
        es: "Encuentra la IP de la cámara (lista del router o i-PRO Configuration Tool / Easy IP Setup).",
      },
      {
        en: "Log into http://<ip> with your admin account.",
        es: "Entra en http://<ip> con tu cuenta de administrador.",
      },
      {
        en: "Setup → Network → ONVIF. add an ONVIF user. Confirm RTSP is enabled.",
        es: "Setup → Network → ONVIF: añade un usuario ONVIF. Confirma que RTSP está activado.",
      },
      {
        en: "Use your admin username and password.",
        es: "Usa tu usuario y contraseña de administrador.",
      },
    ],
    notes: [
      {
        en: "Older Panasonic units use /MediaInput/h264 without the stream suffix.",
        es: "Los equipos Panasonic antiguos usan /MediaInput/h264 sin el sufijo de flujo.",
      },
    ],
  },
  {
    id: "swann",
    name: "Swann",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Dahua-style", es: "Estilo Dahua" }, url: "rtsp://<user>:<pass>@<ip>:554/cam/realmonitor?channel=1&subtype=0" },
      { label: { en: "Channel-style", es: "Estilo por canal" }, url: "rtsp://<user>:<pass>@<ip>:554/ch01/0" },
    ],
    steps: [
      {
        en: "Find the DVR/NVR or camera IP in the Swann app or on the recorder's network screen.",
        es: "Encuentra la IP del DVR/NVR o de la cámara en la app Swann o en la pantalla de red de la grabadora.",
      },
      {
        en: "Enable RTSP/ONVIF in the recorder's Network settings.",
        es: "Activa RTSP/ONVIF en los ajustes de red de la grabadora.",
      },
      {
        en: "Use the device admin account. For an NVR, set channel to the camera you want.",
        es: "Usa la cuenta de administrador del dispositivo. En un NVR, fija el canal de la cámara que quieras.",
      },
    ],
    notes: [
      {
        en: "Many Swann recorders are Dahua-based. If the Dahua URL fails, try the channel-style path.",
        es: "Muchas grabadoras Swann se basan en Dahua. Si la URL estilo Dahua falla, prueba la ruta por canal.",
      },
    ],
  },
  {
    id: "ezviz",
    name: "EZVIZ",
    support: "limited",
    port: 554,
    templates: [
      { label: { en: "Main stream", es: "Flujo principal" }, url: "rtsp://admin:<verificationcode>@<ip>:554/Streaming/Channels/101" },
      { label: { en: "Sub stream", es: "Flujo secundario" }, url: "rtsp://admin:<verificationcode>@<ip>:554/Streaming/Channels/102" },
    ],
    steps: [
      {
        en: "In the EZVIZ app, open the camera → Settings and turn OFF Image Encryption (or note the encryption is the RTSP password).",
        es: "En la app EZVIZ, abre la cámara → Settings y desactiva Image Encryption (o ten en cuenta que el código de cifrado es la contraseña RTSP).",
      },
      {
        en: "The username is admin. The password is the device Verification Code printed on a sticker on the camera.",
        es: "El usuario es admin. La contraseña es el Verification Code del dispositivo, impreso en una etiqueta de la cámara.",
      },
      {
        en: "Find the camera IP in your router. EZVIZ is Hikvision-based, so it uses the Hikvision URL scheme.",
        es: "Encuentra la IP de la cámara en tu router. EZVIZ se basa en Hikvision, así que usa el esquema de URL de Hikvision.",
      },
    ],
    notes: [
      {
        en: "EZVIZ leans cloud-first. Some models only allow RTSP on the local network and only after disabling encryption in the app.",
        es: "EZVIZ apuesta por la nube: algunos modelos solo permiten RTSP en la red local y solo tras desactivar el cifrado en la app.",
      },
    ],
  },
  {
    id: "tiandy",
    name: "Tiandy",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Main stream", es: "Flujo principal" }, url: "rtsp://<user>:<pass>@<ip>:554/0/main" },
      { label: { en: "Sub stream", es: "Flujo secundario" }, url: "rtsp://<user>:<pass>@<ip>:554/0/sub" },
    ],
    steps: [
      {
        en: "Find the camera IP (router list, or Tiandy's search tool).",
        es: "Encuentra la IP de la cámara (lista del router o la herramienta de búsqueda de Tiandy).",
      },
      {
        en: "Log into the web UI and confirm RTSP/ONVIF under Network settings.",
        es: "Entra en la interfaz web y confirma RTSP/ONVIF en los ajustes de red.",
      },
      {
        en: "Use your admin username and password.",
        es: "Usa tu usuario y contraseña de administrador.",
      },
    ],
  },
  {
    id: "geovision",
    name: "GeoVision",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Channel 1", es: "Canal 1" }, url: "rtsp://<user>:<pass>@<ip>:554/CH001.sdp" },
    ],
    steps: [
      {
        en: "Find the camera IP (router list, or the GV-IP Device Utility).",
        es: "Encuentra la IP de la cámara (lista del router o GV-IP Device Utility).",
      },
      {
        en: "Log into the web UI and confirm RTSP/ONVIF are enabled under Network settings.",
        es: "Entra en la interfaz web y confirma que RTSP/ONVIF están activados en los ajustes de red.",
      },
      {
        en: "Use your admin username and password. Change CH001 to the channel you want.",
        es: "Usa tu usuario y contraseña de administrador. Cambia CH001 por el canal que quieras.",
      },
    ],
  },
  {
    id: "pelco",
    name: "Pelco",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Stream 1", es: "Flujo 1" }, url: "rtsp://<user>:<pass>@<ip>:554/stream1" },
      { label: { en: "Stream 2", es: "Flujo 2" }, url: "rtsp://<user>:<pass>@<ip>:554/stream2" },
    ],
    steps: [
      {
        en: "Find the camera IP (router list, or the Pelco Device Utility).",
        es: "Encuentra la IP de la cámara (lista del router o Pelco Device Utility).",
      },
      {
        en: "Log into the web UI. RTSP/ONVIF are supported on Sarix and newer lines.",
        es: "Entra en la interfaz web. RTSP/ONVIF están disponibles en la línea Sarix y posteriores.",
      },
      {
        en: "Use your admin username and password.",
        es: "Usa tu usuario y contraseña de administrador.",
      },
    ],
  },
  {
    id: "sony",
    name: "Sony",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Video 1", es: "Vídeo 1" }, url: "rtsp://<user>:<pass>@<ip>:554/media/video1" },
      { label: { en: "Video 2", es: "Vídeo 2" }, url: "rtsp://<user>:<pass>@<ip>:554/media/video2" },
    ],
    steps: [
      {
        en: "Find the camera IP (router list).",
        es: "Encuentra la IP de la cámara (lista del router).",
      },
      {
        en: "Log into the web UI and confirm RTSP/ONVIF are enabled.",
        es: "Entra en la interfaz web y confirma que RTSP/ONVIF están activados.",
      },
      {
        en: "Use your admin username and password.",
        es: "Usa tu usuario y contraseña de administrador.",
      },
    ],
    notes: [
      {
        en: "Applies to Sony SNC-series network cameras (legacy. Sony exited new camera sales).",
        es: "Se aplica a las cámaras de red Sony serie SNC (legado: Sony dejó de vender cámaras nuevas).",
      },
    ],
  },
  {
    id: "acti",
    name: "ACTi",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Main stream", es: "Flujo principal" }, url: "rtsp://<user>:<pass>@<ip>:554/" },
    ],
    steps: [
      {
        en: "Use the Scan tab above first. ACTi cameras are ONVIF-compliant.",
        es: "Prueba primero la pestaña de escaneo de arriba. Las cámaras ACTi cumplen ONVIF.",
      },
      {
        en: "Otherwise log into the web UI and confirm the RTSP port (some models use 7070 instead of 554).",
        es: "Si no, entra en la interfaz web y confirma el puerto RTSP (algunos modelos usan 7070 en lugar de 554).",
      },
      {
        en: "Use your admin username and password.",
        es: "Usa tu usuario y contraseña de administrador.",
      },
    ],
    notes: [
      {
        en: "RTSP port is 554 on most models but 7070 on some older ones.",
        es: "El puerto RTSP es 554 en la mayoría de los modelos, pero 7070 en algunos antiguos.",
      },
    ],
  },
  {
    id: "mobotix",
    name: "Mobotix",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "H.264 stream", es: "Flujo H.264" }, url: "rtsp://<user>:<pass>@<ip>/mobotix.sdp" },
    ],
    steps: [
      {
        en: "In the Mobotix camera UI, enable the RTSP server under Admin Menu → Integration → RTSP / Multicast.",
        es: "En la interfaz de la cámara Mobotix, activa el servidor RTSP en Admin Menu → Integration → RTSP / Multicast.",
      },
      {
        en: "Find the camera IP (router list, or MxManagementCenter).",
        es: "Encuentra la IP de la cámara (lista del router o MxManagementCenter).",
      },
      {
        en: "Use your admin username and password.",
        es: "Usa tu usuario y contraseña de administrador.",
      },
    ],
    notes: [
      {
        en: "RTSP is off by default on Mobotix. You must enable the RTSP server first. ONVIF/Scan also works once enabled.",
        es: "RTSP viene desactivado en Mobotix: primero debes activar el servidor RTSP. ONVIF y el escaneo también funcionan una vez activado.",
      },
    ],
  },
  {
    id: "generic_onvif",
    name: "Generic ONVIF / other",
    support: "yes",
    port: 554,
    templates: [
      { label: { en: "Common path", es: "Ruta común" }, url: "rtsp://<user>:<pass>@<ip>:554/onvif1" },
      { label: { en: "Alt path", es: "Ruta alternativa" }, url: "rtsp://<user>:<pass>@<ip>:554/stream1" },
    ],
    steps: [
      {
        en: "Use the Scan network tab above. ONVIF cameras advertise themselves and Nurby can discover the IP + stream URL automatically.",
        es: "Usa la pestaña de escaneo de red de arriba. Las cámaras ONVIF se anuncian solas y Nurby puede descubrir la IP y la URL del flujo automáticamente.",
      },
      {
        en: "If the scan finds it, just enter the camera's username and password.",
        es: "Si el escaneo la encuentra, solo tienes que introducir el usuario y la contraseña de la cámara.",
      },
      {
        en: "If you have to type it manually, check the maker's manual for the RTSP path, then add it after rtsp://<user>:<pass>@<ip>:554/.",
        es: "Si tienes que escribirla a mano, consulta el manual del fabricante para la ruta RTSP y añádela tras rtsp://<user>:<pass>@<ip>:554/.",
      },
    ],
    notes: [
      {
        en: "When in doubt, try the Scan tab first. It removes the guesswork for any ONVIF-compliant camera.",
        es: "Ante la duda, prueba primero la pestaña de escaneo: elimina las conjeturas con cualquier cámara compatible con ONVIF.",
      },
    ],
  },
  {
    id: "cloud_only",
    name: "Ring / Nest / Arlo (cloud)",
    support: "no",
    templates: [],
    steps: [
      {
        en: "These brands lock the video to their own cloud app and do NOT expose a direct RTSP/ONVIF stream.",
        es: "Estas marcas atan el vídeo a su propia app de nube y NO exponen un flujo RTSP/ONVIF directo.",
      },
      {
        en: "To use them with Nurby you need a bridge such as Scrypted, which re-exposes the feed as RTSP. that is an advanced, separate setup.",
        es: "Para usarlas con Nurby necesitas un puente como Scrypted, que vuelve a exponer la señal como RTSP; es una configuración avanzada y aparte.",
      },
      {
        en: "If you want a plug-and-play camera for Nurby, a wired ONVIF/RTSP camera (Hikvision, Dahua, Reolink PoE, Amcrest, Axis) is the easy path.",
        es: "Si quieres una cámara plug-and-play para Nurby, lo fácil es una cámara ONVIF/RTSP cableada (Hikvision, Dahua, Reolink PoE, Amcrest, Axis).",
      },
    ],
    notes: [
      {
        en: "No native RTSP. consider a Scrypted bridge or a different camera for direct use.",
        es: "Sin RTSP nativo: considera un puente Scrypted u otra cámara para uso directo.",
      },
    ],
  },
];

export function findBrand(id: string): CameraBrand | undefined {
  return CAMERA_BRANDS.find((b) => b.id === id);
}

/** Serve a piece of brand data in the requested locale, English fallback. */
export function localizedText(
  text: LocalizedText,
  locale: string | null | undefined,
): string {
  return locale === "es" && text.es ? text.es : text.en;
}

export function brandSteps(
  brand: CameraBrand,
  locale: string | null | undefined,
): string[] {
  return brand.steps.map((step) => localizedText(step, locale));
}

export function brandNotes(
  brand: CameraBrand,
  locale: string | null | undefined,
): string[] {
  return (brand.notes ?? []).map((note) => localizedText(note, locale));
}

export function templateLabel(
  template: RtspTemplate,
  locale: string | null | undefined,
): string {
  return localizedText(template.label, locale);
}

/**
 * Locale-coverage contract for the brand data. English source must always
 * be present, and a brand field is either fully translated into Spanish or
 * not translated at all — a half-translated step list would be worse than
 * an English one.
 */
export function validateCameraBrands(): string[] {
  const problems: string[] = [];
  const checkField = (brandId: string, field: string, items: LocalizedText[]) => {
    if (items.some((item) => !item.en.trim())) {
      problems.push(`${brandId}.${field}: missing English source`);
    }
    const esCount = items.filter((item) => item.es).length;
    if (esCount > 0 && esCount !== items.length) {
      problems.push(
        `${brandId}.${field}: partial Spanish coverage (${esCount}/${items.length})`,
      );
    }
  };
  for (const brand of CAMERA_BRANDS) {
    checkField(brand.id, "steps", brand.steps);
    if (brand.notes) checkField(brand.id, "notes", brand.notes);
    for (const template of brand.templates) {
      if (!template.label.en.trim()) {
        problems.push(`${brand.id}.templates: missing English label`);
      }
    }
  }
  return problems;
}
