import { useEffect, useRef, useState } from "react";
import {
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { TodoApiError, type AuthUser, type Session } from "../todos/todoApi";
import { analytics } from "../analytics";

export type AuthApi = {
  signup: (username: string, password: string, realName?: string) => Promise<AuthUser>;
  login: (username: string, password: string) => Promise<Session>;
};

type Mode = "signin" | "signup";

const ACCOUNT_ERROR = "Check the username and password and try again.";
const EMPTY_ERROR = "Enter a username and password.";
const CREATED_MESSAGE = "Account created. Please sign in.";

function authError(error: unknown, operation: Mode): string {
  if (error instanceof TodoApiError) {
    if (error.kind === "validation" || error.kind === "invalid-data") return ACCOUNT_ERROR;
    if (error.kind === "auth-required") return error.message;
    return operation === "signin" ? "Could not sign in." : "Could not create account.";
  }
  return operation === "signin" ? "Could not sign in." : "Could not create account.";
}

export function AuthScreen({
  signup,
  login,
  onAuthenticated,
}: {
  signup: AuthApi["signup"];
  login: AuthApi["login"];
  onAuthenticated: (session: Session) => void;
}): React.JSX.Element {
  const [mode, setMode] = useState<Mode>("signin");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [realName, setRealName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const busy = useRef(false);

  // One view per mount and per mode switch (Phase 30a funnel entry).
  useEffect(() => {
    analytics.track("auth_screen_viewed", { mode });
  }, [mode]);

  const submit = () => {
    if (busy.current) return;
    if (username.trim() === "" || password === "") {
      setError(EMPTY_ERROR);
      return;
    }
    busy.current = true;
    analytics.track(mode === "signin" ? "signin_submitted" : "signup_submitted", {});
    setPending(true);
    setError(null);
    const attempt = mode === "signin" ? login(username, password)
      : realName.trim() ? signup(username, password, realName.trim()) : signup(username, password);
    void attempt.then(
      (result) => {
        if (mode === "signin") {
          onAuthenticated(result as Session);
        } else {
          analytics.identify((result as AuthUser).id);
          setMode("signin");
          setUsername(username);
          setPassword("");
          setRealName("");
          setError(CREATED_MESSAGE);
        }
      },
      (reason: unknown) => {
        setError(authError(reason, mode));
      },
    ).finally(() => {
      busy.current = false;
      setPending(false);
    });
  };

  const toggleMode = () => {
    if (busy.current || pending) return;
    setError(null);
    setRealName("");
    setMode((current) => (current === "signin" ? "signup" : "signin"));
  };

  return (
    <SafeAreaView style={styles.safeArea}>
      <ScrollView
        automaticallyAdjustKeyboardInsets
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={styles.content}
      >
        <Text accessibilityRole="header" style={styles.heading}>
          {mode === "signin" ? "Sign in" : "Create account"}
        </Text>
        {error && (
          <Text accessibilityRole="alert" style={styles.error}>
            {error}
          </Text>
        )}
        <View style={styles.form}>
          {mode === "signup" && <>
            <Text style={styles.fieldLabel}>Real name (optional)</Text>
            <TextInput
              accessibilityLabel="Real name (optional)"
              testID="e2e-auth-real-name"
              editable={!pending}
              value={realName}
              maxLength={100}
              autoComplete="name"
              autoCapitalize="words"
              autoCorrect={false}
              onChangeText={setRealName}
              placeholder="Your name"
              style={styles.input}
            />
          </>}
          <Text style={styles.fieldLabel}>Username</Text>
          <TextInput
            accessibilityLabel="Username"
            testID="e2e-auth-username"
            editable={!pending}
            value={username}
            autoCapitalize="none"
            autoCorrect={false}
            onChangeText={setUsername}
            placeholder="Username"
            style={styles.input}
          />
          <Text style={styles.fieldLabel}>Password</Text>
          <TextInput
            accessibilityLabel="Password"
            testID="e2e-auth-password"
            editable={!pending}
            value={password}
            secureTextEntry
            autoCapitalize="none"
            autoCorrect={false}
            onChangeText={setPassword}
            onSubmitEditing={submit}
            placeholder="Password"
            style={styles.input}
          />
          <Pressable
            accessibilityRole="button"
            testID="e2e-auth-submit"
            accessibilityLabel={mode === "signin" ? "Sign in" : "Create account"}
            disabled={pending}
            style={styles.submitButton}
            onPress={submit}
          >
            <Text style={styles.submitButtonText}>
              {mode === "signin" ? "Sign in" : "Create account"}
            </Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={
              mode === "signin" ? "New here? Create an account." : "Have an account? Sign in."
            }
            disabled={pending}
            style={styles.toggleButton}
            onPress={toggleMode}
          >
            <Text style={styles.toggleButtonText}>
              {mode === "signin" ? "New here? Create an account." : "Have an account? Sign in."}
            </Text>
          </Pressable>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  content: {
    flexGrow: 1,
    gap: 16,
    padding: 24,
  },
  heading: {
    color: "#172033",
    fontSize: 32,
    fontWeight: "700",
  },
  form: {
    gap: 10,
  },
  fieldLabel: {
    color: "#42526b",
    fontSize: 15,
    fontWeight: "600",
  },
  input: {
    borderColor: "#aeb9c9",
    borderRadius: 10,
    borderWidth: 1,
    color: "#172033",
    fontSize: 17,
    minHeight: 48,
    paddingHorizontal: 14,
  },
  submitButton: {
    alignItems: "center",
    backgroundColor: "#2457d6",
    borderRadius: 10,
    justifyContent: "center",
    minHeight: 48,
    minWidth: 44,
    paddingHorizontal: 16,
  },
  submitButtonText: {
    color: "#ffffff",
    fontSize: 16,
    fontWeight: "700",
  },
  toggleButton: {
    alignItems: "center",
    borderColor: "#aeb9c9",
    borderRadius: 10,
    borderWidth: 1,
    justifyContent: "center",
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 16,
  },
  toggleButtonText: {
    color: "#173da0",
    fontSize: 16,
    fontWeight: "700",
  },
  error: {
    color: "#b42318",
    fontSize: 15,
  },
});
