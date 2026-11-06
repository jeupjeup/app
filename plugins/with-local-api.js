const { withDangerousMod, withInfoPlist } = require('expo/config-plugins');
const fs = require('node:fs/promises');
const path = require('node:path');

module.exports = function withLocalApi(config) {
    config = withInfoPlist(config, config => {
        config.modResults.NSLocalNetworkUsageDescription = '개발 서버에 연결해 저장한 정보를 동기화합니다.';
        config.modResults.NSAppTransportSecurity = {
            ...config.modResults.NSAppTransportSecurity,
            NSAllowsLocalNetworking: true
        };
        return config;
    });
    return withDangerousMod(config, ['android', async config => {
        const directory = path.join(config.modRequest.platformProjectRoot, 'app/src/debug');
        await fs.mkdir(directory, { recursive: true });
        const manifest = path.join(directory, 'AndroidManifest.xml');
        const existing = await fs.readFile(manifest, 'utf8').catch(error => { if (error.code === 'ENOENT') return null; throw error; });
        const source = existing || '<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application /></manifest>';
        const updated = source.replace(/<application\b([^>]*)>/, (match, attributes) => {
            const attrs = attributes.replace(/\sandroid:usesCleartextTraffic="[^"]*"/g, '');
            return `<application android:usesCleartextTraffic="true"${attrs}>`;
        });
        await fs.writeFile(manifest, updated);
        return config;
    }]);
};
