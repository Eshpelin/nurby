import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/core/server_config.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  Future<ServerConfig> makeConfig() async {
    SharedPreferences.setMockInitialValues({});
    return ServerConfig(await SharedPreferences.getInstance());
  }

  test('normalizes trailing slash and missing scheme', () async {
    final config = await makeConfig();

    await config.setBaseUrl('http://10.0.0.5:8000/');
    expect(config.baseUrl, 'http://10.0.0.5:8000');

    await config.setBaseUrl('192.168.1.50:8000');
    expect(config.baseUrl, 'http://192.168.1.50:8000');

    await config.setBaseUrl('https://nurby.example.com');
    expect(config.baseUrl, 'https://nurby.example.com');
  });

  test('wsBaseUrl swaps scheme', () async {
    final config = await makeConfig();
    await config.setBaseUrl('https://nurby.example.com');
    expect(config.wsBaseUrl, 'wss://nurby.example.com');

    await config.setBaseUrl('http://10.0.0.5:8000');
    expect(config.wsBaseUrl, 'ws://10.0.0.5:8000');
  });

  test('clear removes the pointer', () async {
    final config = await makeConfig();
    await config.setBaseUrl('http://10.0.0.5:8000');
    await config.clear();
    expect(config.baseUrl, isNull);
    expect(config.wsBaseUrl, isNull);
  });
}
