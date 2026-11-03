const { withXcodeProject } = require("expo/config-plugins");
const fs = require("node:fs");
const path = require("node:path");
const plist = require("@expo/plist").default;

// expo-sharing names its extension after the technical target by default.
module.exports = function withShareExtensionName(config) {
    // The extension files are generated in the earlier dangerous-mod phase.
    return withXcodeProject(config, config => {
        if (config.modRequest.introspect) return config;
        const filename = path.join(config.modRequest.platformProjectRoot, "expo-sharing-extension", "Info.plist");
        const info = plist.parse(fs.readFileSync(filename, "utf8"));
        info.CFBundleDisplayName = config.name;
        fs.writeFileSync(filename, plist.build(info));
        for (const section of Object.values(config.modResults.pbxXCBuildConfigurationSection())) {
            const settings = section.buildSettings;
            if (settings?.PRODUCT_BUNDLE_IDENTIFIER?.replace(/^"|"$/g, "") === `${config.ios.bundleIdentifier}.ShareExtension`) {
                settings.INFOPLIST_KEY_CFBundleDisplayName = JSON.stringify(config.name);
            }
        }
        return config;
    });
};
