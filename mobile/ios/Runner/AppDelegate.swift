import Flutter
import UIKit
import workmanager

@main
@objc class AppDelegate: FlutterAppDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    GeneratedPluginRegistrant.register(with: self)

    // workmanager: background isolates need the plugin registrant too.
    WorkmanagerPlugin.setPluginRegistrantCallback { registry in
      GeneratedPluginRegistrant.register(with: registry)
    }
    // BGTaskScheduler identifier must be registered before didFinishLaunching
    // returns. Identifier matches kBackgroundTaskId in lib/core/push.dart and
    // BGTaskSchedulerPermittedIdentifiers in Info.plist. The 15-minute
    // frequency is a hint; iOS schedules refreshes on its own cadence.
    WorkmanagerPlugin.registerPeriodicTask(
      withIdentifier: "com.nurby.nurbyMobile.alertcheck",
      frequency: NSNumber(value: 15 * 60))

    // flutter_local_notifications: present notifications while foregrounded.
    if #available(iOS 10.0, *) {
      UNUserNotificationCenter.current().delegate = self as UNUserNotificationCenterDelegate
    }

    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }
}
