import { useState } from "react";
import { StyleSheet, Switch, Text, View } from "react-native";
import type { Analytics } from "./analytics";
import { analytics as defaultAnalytics } from "./index";

export function AnalyticsConsentSwitch({
  analytics = defaultAnalytics,
}: {
  analytics?: Analytics;
}): React.JSX.Element | null {
  const [state, setState] = useState(() => analytics.consent());
  if (!state.available) return null;
  return (
    <View style={styles.row}>
      <Text style={styles.label}>
        {state.gpc ? "Off: your browser sends Global Privacy Control." : "Share usage analytics"}
      </Text>
      <Switch
        accessibilityLabel="Share usage analytics"
        value={state.enabled}
        disabled={state.gpc}
        onValueChange={(next) => {
          analytics.setConsent(next);
          setState(analytics.consent());
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    alignItems: "center",
    flexDirection: "row",
    gap: 12,
    justifyContent: "space-between",
    paddingHorizontal: 24,
    paddingVertical: 4,
  },
  label: {
    color: "#42526b",
    flex: 1,
    fontSize: 14,
  },
});
