// frontend/config-overrides.js

module.exports = {
  webpack: function (config, env) {
    return config;
  },
  devServer: function (configFunction) {
    return function (proxy, allowedHost) {
      const config = configFunction(proxy, allowedHost);

      // Fix for allowedHosts error in newer Node.js versions
      config.allowedHosts = 'all';

      return config;
    };
  }
};