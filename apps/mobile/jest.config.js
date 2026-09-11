module.exports = {
  preset: "jest-expo",
  testMatch: ["**/*.test.ts?(x)"],
  // Reproduced defect: pinned assistant-ui/AG-UI packages ship ESM
  // (type: module) that Jest must transform; the default jest-expo
  // allowlist ignores them and the suite fails with
  // "Cannot use import statement outside a module".
  transformIgnorePatterns: [
    "/node_modules/(?!(.pnpm|react-native|@react-native|@react-native-community|expo|@expo|@expo-google-fonts|react-navigation|@react-navigation|@sentry/react-native|native-base|standard-navigation|@assistant-ui|@ag-ui|assistant-stream|uuid|rxjs))/",
    "/node_modules/react-native-reanimated/plugin/",
    "/node_modules/@react-native/babel-preset/",
  ],
};
