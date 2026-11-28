package com.mahoraga.capabilitylab;

import android.Manifest;
import android.app.ActivityManager;
import android.app.job.JobScheduler;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.hardware.Sensor;
import android.hardware.SensorManager;
import android.hardware.input.InputManager;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbManager;
import android.media.AudioRecord;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Environment;
import android.os.PowerManager;
import android.os.StatFs;
import android.view.InputDevice;

import java.io.File;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public final class AndroidCapabilityProbe {
    private final Context context;
    private final PackageManager packageManager;

    public AndroidCapabilityProbe(Context context) {
        this.context = context.getApplicationContext();
        this.packageManager = this.context.getPackageManager();
    }

    public CapabilityReport collect() {
        Map<String, Object> device = new LinkedHashMap<>();
        device.put("manufacturer", Build.MANUFACTURER);
        device.put("model", Build.MODEL);
        device.put("device", Build.DEVICE);
        device.put("android_release", Build.VERSION.RELEASE);
        device.put("api_level", Build.VERSION.SDK_INT);
        device.put("app_target_sdk", context.getApplicationInfo().targetSdkVersion);
        device.put("resource_snapshot", collectResourceSnapshot());

        Map<String, Object> capabilities = new LinkedHashMap<>();
        add(capabilities, "termux_package", packageProbe("com.termux"));
        add(capabilities, "shizuku_package", shizukuProbe());
        add(capabilities, "sensor_inventory", sensorProbe());
        add(capabilities, "input_devices", inputProbe());
        add(capabilities, "usb_host", usbProbe());
        add(capabilities, "bluetooth", bluetoothProbe());
        add(capabilities, "camera_permission_and_feature", cameraProbe());
        add(capabilities, "microphone_permission_and_feature", microphoneProbe());
        add(capabilities, "camerax_sdk", cameraXSdkProbe());
        add(capabilities, "media_projection", mediaProjectionProbe());
        add(capabilities, "storage_access_framework", safProbe());
        add(capabilities, "workmanager_library", workManagerProbe());
        add(capabilities, "jobscheduler_service", jobSchedulerProbe());
        add(capabilities, "foreground_service_declarations", foregroundServiceProbe());
        add(capabilities, "user_initiated_data_transfer_api", uidtProbe());

        return new CapabilityReport(device, capabilities);
    }

    private Map<String, Object> collectResourceSnapshot() {
        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("supported_abis", new ArrayList<>(Arrays.asList(Build.SUPPORTED_ABIS)));
        snapshot.put("hardware", Build.HARDWARE);
        snapshot.put("soc_model", Build.VERSION.SDK_INT >= 31 ? Build.SOC_MODEL : null);
        snapshot.put("processor_count", Runtime.getRuntime().availableProcessors());
        snapshot.put("processor_count_scope", "runtime_visible_logical_processors");
        ActivityManager activityManager = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
        if (activityManager != null) {
            ActivityManager.MemoryInfo memory = new ActivityManager.MemoryInfo();
            activityManager.getMemoryInfo(memory);
            snapshot.put("memory", fields("scope", "device_memory", "total_bytes", memory.totalMem,
                    "available_bytes", memory.availMem, "threshold_bytes", memory.threshold,
                    "low_memory", memory.lowMemory));
        } else snapshot.put("memory", fields("scope", "device_memory", "status", "temporarily_unavailable"));
        File dataDirectory = Environment.getDataDirectory();
        try {
            StatFs storage = new StatFs(dataDirectory.getPath());
            snapshot.put("storage", fields("scope", "data_partition", "path", dataDirectory.getPath(),
                    "total_bytes", storage.getTotalBytes(), "available_bytes", storage.getAvailableBytes()));
        } catch (RuntimeException error) {
            snapshot.put("storage", fields("scope", "data_partition", "status", "temporarily_unavailable",
                    "reason", error.getClass().getSimpleName()));
        }
        PowerManager powerManager = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
        if (Build.VERSION.SDK_INT >= 29 && powerManager != null) {
            try {
                int thermalStatus = powerManager.getCurrentThermalStatus();
                snapshot.put("thermal", fields("metric", "thermal_status", "status", thermalStatusName(thermalStatus),
                        "status_code", thermalStatus, "source", "PowerManager.getCurrentThermalStatus"));
            } catch (RuntimeException error) {
                snapshot.put("thermal", fields("metric", "thermal_status", "status", "temporarily_unavailable",
                        "reason", error.getClass().getSimpleName()));
            }
        } else snapshot.put("thermal", fields("metric", "thermal_status", "status", "unsupported", "minimum_api", 29,
                "api_level", Build.VERSION.SDK_INT));
        snapshot.put("gpu", fields("status", "not_probed",
                "reason", "GPU inventory requires a separately initialized graphics context."));
        return snapshot;
    }

    private static String thermalStatusName(int status) {
        switch (status) {
            case PowerManager.THERMAL_STATUS_NONE: return "none";
            case PowerManager.THERMAL_STATUS_LIGHT: return "light";
            case PowerManager.THERMAL_STATUS_MODERATE: return "moderate";
            case PowerManager.THERMAL_STATUS_SEVERE: return "severe";
            case PowerManager.THERMAL_STATUS_CRITICAL: return "critical";
            case PowerManager.THERMAL_STATUS_EMERGENCY: return "emergency";
            case PowerManager.THERMAL_STATUS_SHUTDOWN: return "shutdown";
            default: return "unknown";
        }
    }

    private boolean isPermissionDeclared(String permission) {
        try {
            PackageInfo info = packageManager.getPackageInfo(context.getPackageName(), PackageManager.GET_PERMISSIONS);
            if (info.requestedPermissions == null) return false;
            for (String declared : info.requestedPermissions) if (permission.equals(declared)) return true;
        } catch (PackageManager.NameNotFoundException | SecurityException ignored) {
            // Unreadable manifest metadata never implies a permission grant.
        }
        return false;
    }

    private static void add(
            Map<String, Object> target, String id, Map<String, Object> value) {
        target.put(id, value);
    }

    private static Map<String, Object> fields(Object... pairs) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int index = 0; index + 1 < pairs.length; index += 2) {
            result.put((String) pairs[index], pairs[index + 1]);
        }
        return result;
    }

    private Map<String, Object> entry(
            CapabilityState.Status status, String detail, Object evidence) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", status.name());
        result.put("detail", detail);
        if (evidence != null) result.put("evidence", evidence);
        return result;
    }

    private Map<String, Object> packageProbe(String packageName) {
        try {
            PackageInfo info = packageManager.getPackageInfo(packageName, 0);
            Map<String, Object> evidence = new LinkedHashMap<>();
            evidence.put("package", packageName);
            evidence.put("version_name", info.versionName);
            evidence.put("version_code", Build.VERSION.SDK_INT >= 28
                    ? info.getLongVersionCode() : info.versionCode);
            return entry(
                    CapabilityState.Status.AVAILABLE,
                    "Pacote visível e instalado; nenhuma chamada externa foi iniciada.",
                    evidence);
        } catch (PackageManager.NameNotFoundException | SecurityException error) {
            return entry(
                    CapabilityState.Status.TEMPORARILY_UNAVAILABLE,
                    "Pacote ausente ou não visível para este inventário.",
                    fields("package", packageName));
        }
    }

    private Map<String, Object> shizukuProbe() {
        Map<String, Object> packageState = packageProbe("moe.shizuku.privileged.api");
        if (CapabilityState.Status.AVAILABLE.name().equals(packageState.get("status"))) {
            return entry(
                    CapabilityState.Status.REQUIRES_USER_ACTION,
                    "Shizuku instalado; Binder/UserService não foi vinculado nem autorizado nesta versão read-only.",
                    packageState.get("evidence"));
        }
        return packageState;
    }

    private Map<String, Object> sensorProbe() {
        SensorManager manager = (SensorManager) context.getSystemService(Context.SENSOR_SERVICE);
        if (manager == null) {
            return entry(CapabilityState.Status.FAILED, "SensorManager indisponível.", null);
        }
        List<Map<String, Object>> sensors = new ArrayList<>();
        for (Sensor sensor : manager.getSensorList(Sensor.TYPE_ALL)) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("type", sensor.getType());
            item.put("name", sensor.getName());
            item.put("vendor", sensor.getVendor());
            item.put("wake_up", sensor.isWakeUpSensor());
            item.put("min_delay_us", sensor.getMinDelay());
            sensors.add(item);
        }
        return entry(
                sensors.isEmpty()
                        ? CapabilityState.Status.TEMPORARILY_UNAVAILABLE
                        : CapabilityState.Status.AVAILABLE,
                "Inventário de metadados somente; nenhum listener ou amostragem iniciado.",
                sensors);
    }

    private Map<String, Object> inputProbe() {
        InputManager manager = (InputManager) context.getSystemService(Context.INPUT_SERVICE);
        if (manager == null) {
            return entry(CapabilityState.Status.FAILED, "InputManager indisponível.", null);
        }
        List<Map<String, Object>> devices = new ArrayList<>();
        for (int id : manager.getInputDeviceIds()) {
            InputDevice device = manager.getInputDevice(id);
            if (device == null) continue;
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("id", device.getId());
            item.put("name", device.getName());
            item.put("descriptor", device.getDescriptor());
            item.put("vendor_id", device.getVendorId());
            item.put("product_id", device.getProductId());
            item.put("sources", device.getSources());
            item.put("is_virtual", device.isVirtual());
            devices.add(item);
        }
        return entry(
                CapabilityState.Status.AVAILABLE,
                "Inventário de dispositivos de entrada; nenhum evento foi capturado.",
                devices);
    }

    private Map<String, Object> usbProbe() {
        UsbManager manager = (UsbManager) context.getSystemService(Context.USB_SERVICE);
        if (manager == null) {
            return entry(CapabilityState.Status.FAILED, "UsbManager indisponível.", null);
        }
        List<Map<String, Object>> devices = new ArrayList<>();
        for (UsbDevice device : manager.getDeviceList().values()) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("device_name", device.getDeviceName());
            item.put("vendor_id", device.getVendorId());
            item.put("product_id", device.getProductId());
            item.put("interface_count", device.getInterfaceCount());
            devices.add(item);
        }
        boolean supported = packageManager.hasSystemFeature(PackageManager.FEATURE_USB_HOST);
        return entry(
                supported ? CapabilityState.Status.AVAILABLE : CapabilityState.Status.UNSUPPORTED,
                "Enumeração USB somente; não foi solicitada permissão para abrir dispositivos.",
                devices);
    }

    private Map<String, Object> bluetoothProbe() {
        boolean supported = packageManager.hasSystemFeature(PackageManager.FEATURE_BLUETOOTH);
        if (!supported) {
            return entry(CapabilityState.Status.UNSUPPORTED, "Bluetooth não declarado como recurso do dispositivo.", null);
        }
        if (Build.VERSION.SDK_INT >= 31) {
            boolean declared = isPermissionDeclared(Manifest.permission.BLUETOOTH_CONNECT);
            boolean granted = declared && context.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)
                    == PackageManager.PERMISSION_GRANTED;
            return entry(CapabilityState.permission(true, declared, granted),
                    declared ? "Bluetooth presente; conexões não são inspecionadas nesta versão."
                            : "BLUETOOTH_CONNECT não está declarado; recurso bloqueado pela política do manifesto atual.",
                    fields("permission", Manifest.permission.BLUETOOTH_CONNECT,
                            "permission_declared", declared, "permission_granted", granted));
        }
        return entry(CapabilityState.Status.AVAILABLE,
                "Bluetooth presente; inventário de conexões não é executado nesta versão.",
                fields("permission_required_on_this_api", false));
    }

    private Map<String, Object> cameraProbe() {
        boolean feature = packageManager.hasSystemFeature(PackageManager.FEATURE_CAMERA_ANY);
        boolean declared = isPermissionDeclared(Manifest.permission.CAMERA);
        boolean granted = declared && context.checkSelfPermission(Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED;
        return entry(CapabilityState.permission(feature, declared, granted),
                declared ? "Somente consulta de feature/permissão; câmera nunca é aberta."
                        : "CAMERA não está declarado; recurso bloqueado pela política do manifesto atual.",
                fields("camera_feature", feature, "required_permission", Manifest.permission.CAMERA,
                        "permission_declared", declared, "permission_granted", granted));
    }

    private Map<String, Object> microphoneProbe() {
        boolean feature = packageManager.hasSystemFeature(PackageManager.FEATURE_MICROPHONE);
        boolean declared = isPermissionDeclared(Manifest.permission.RECORD_AUDIO);
        boolean granted = declared && context.checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                == PackageManager.PERMISSION_GRANTED;
        return entry(CapabilityState.permission(feature, declared, granted),
                declared ? "Somente consulta de feature/permissão; AudioRecord nunca é iniciado."
                        : "RECORD_AUDIO não está declarado; recurso bloqueado pela política do manifesto atual.",
                fields("audio_record_class", AudioRecord.class.getName(),
                        "microphone_feature", feature, "required_permission", Manifest.permission.RECORD_AUDIO,
                        "permission_declared", declared, "permission_granted", granted));
    }

    private static final String CAMERAX_PROVIDER_CLASS =
            "androidx.camera.lifecycle.ProcessCameraProvider";

    private Map<String, Object> cameraXSdkProbe() {
        boolean linked;
        try {
            Class.forName(CAMERAX_PROVIDER_CLASS, false, context.getClassLoader());
            linked = true;
        } catch (ClassNotFoundException | LinkageError error) {
            linked = false;
        }
        return entry(linked ? CapabilityState.Status.AVAILABLE : CapabilityState.Status.TEMPORARILY_UNAVAILABLE,
                linked ? "ProcessCameraProvider está no classpath; nenhuma câmera foi aberta."
                        : "CameraX lifecycle provider não está empacotado; nenhuma dependência baixada dinamicamente.",
                fields("provider_class", CAMERAX_PROVIDER_CLASS, "linked", linked));
    }

    private Map<String, Object> mediaProjectionProbe() {
        MediaProjectionManager manager = (MediaProjectionManager)
                context.getSystemService(Context.MEDIA_PROJECTION_SERVICE);
        return entry(
                manager == null ? CapabilityState.Status.UNSUPPORTED
                        : CapabilityState.Status.REQUIRES_USER_ACTION,
                "A API está disponível; consentimento e serviço foreground não foram solicitados/iniciados.",
                null);
    }

    private Map<String, Object> safProbe() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*");
        boolean resolvable = intent.resolveActivity(packageManager) != null;
        return entry(
                resolvable ? CapabilityState.Status.AVAILABLE
                        : CapabilityState.Status.TEMPORARILY_UNAVAILABLE,
                "Somente resolução de intent; seletor de arquivos não foi aberto.",
                fields("open_document_resolvable", resolvable));
    }

    private Map<String, Object> workManagerProbe() {
        boolean linked;
        try {
            Class.forName("androidx.work.WorkManager", false, context.getClassLoader());
            linked = true;
        } catch (ClassNotFoundException | LinkageError error) {
            linked = false;
        }
        return entry(
                linked ? CapabilityState.Status.AVAILABLE : CapabilityState.Status.TEMPORARILY_UNAVAILABLE,
                linked ? "Biblioteca WorkManager presente; não foi inicializada e nenhum job foi enfileirado."
                        : "WorkManager não está empacotado no APK v0.1; JobScheduler é inspecionado separadamente.",
                null);
    }

    private Map<String, Object> jobSchedulerProbe() {
        JobScheduler scheduler = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        return entry(
                scheduler == null ? CapabilityState.Status.UNSUPPORTED : CapabilityState.Status.AVAILABLE,
                "Serviço JobScheduler consultado; nenhum job foi criado, cancelado ou enumerado.",
                null);
    }

    private Map<String, Object> foregroundServiceProbe() {
        List<Map<String, Object>> declared = new ArrayList<>();
        try {
            PackageInfo info = packageManager.getPackageInfo(
                    context.getPackageName(), PackageManager.GET_SERVICES);
            if (info.services != null) {
                for (ServiceInfo service : info.services) {
                    Map<String, Object> item = new LinkedHashMap<>();
                    item.put("name", service.name);
                    item.put("foreground_service_type", Build.VERSION.SDK_INT >= 29
                            ? service.getForegroundServiceType() : 0);
                    declared.add(item);
                }
            }
            return entry(
                    CapabilityState.Status.AVAILABLE,
                    "Inspeciona somente os services declarados neste APK; nenhum service foi iniciado.",
                    declared);
        } catch (PackageManager.NameNotFoundException | SecurityException error) {
            return entry(CapabilityState.Status.FAILED, "Não foi possível ler o próprio manifest.", null);
        }
    }

    private Map<String, Object> uidtProbe() {
        boolean available = Build.VERSION.SDK_INT >= 34;
        return entry(
                available ? CapabilityState.Status.AVAILABLE : CapabilityState.Status.UNSUPPORTED,
                "Verifica apenas o nível de API; nenhum User-Initiated Data Transfer Job foi agendado.",
                fields("minimum_api", 34, "api_level", Build.VERSION.SDK_INT));
    }
}
