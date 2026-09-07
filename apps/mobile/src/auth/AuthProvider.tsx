import { useCallback, useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { useQueryClient } from "@tanstack/react-query";
import { TodoScreen } from "../TodoScreen";
import {
  fetchMe,
  login,
  logout,
  signup,
  TodoApiError,
  type AuthUser,
  type Session,
  type TodoRequestOptions,
} from "../todos/todoApi";
import { createAuthenticatedApi, defaultTransport, type TodoTransport } from "./authenticatedApi";
import { AuthScreen } from "./AuthScreen";
import { tokenStorage, type TokenStorage } from "./tokenStorage";

export type ProviderAuthApi = {
  signup: (username: string, password: string) => Promise<AuthUser>;
  login: (username: string, password: string) => Promise<Session>;
  logout: (options?: TodoRequestOptions) => Promise<void>;
  fetchMe: (options?: TodoRequestOptions) => Promise<AuthUser>;
};

const defaultAuthApi: ProviderAuthApi = { signup, login, logout, fetchMe };

type Status = "unknown" | "signed-out" | "signed-in";

export function AuthProvider({
  authApi = defaultAuthApi,
  storage = tokenStorage,
  transport = defaultTransport,
}: {
  authApi?: ProviderAuthApi;
  storage?: TokenStorage;
  transport?: TodoTransport;
} = {}): React.JSX.Element {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status>("unknown");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    let mounted = true;
    void (async () => {
      let stored: string | null;
      try {
        stored = await storage.get();
      } catch {
        if (mounted) setStatus("signed-out");
        return;
      }
      if (!mounted) return;
      if (stored === null) {
        setStatus("signed-out");
        return;
      }
      try {
        const restored = await authApi.fetchMe({ token: stored });
        if (!mounted) return;
        setToken(stored);
        setUser(restored);
        setStatus("signed-in");
      } catch (error) {
        if (!mounted) return;
        if (error instanceof TodoApiError) {
          try {
            await storage.clear();
          } catch {
            // Best effort: local state still settles below.
          }
        }
        setStatus("signed-out");
      }
    })();
    return () => {
      mounted = false;
    };
  }, [authApi, storage]);

  const signOut = useCallback(() => {
    if (signingOut || token === null) return;
    setSigningOut(true);
    const current = token;
    void (async () => {
      try {
        await authApi.logout({ token: current });
      } catch {
        // Best effort: local state clears regardless of server reachability.
      } finally {
        try {
          await storage.clear();
        } catch {
          // Best effort: local state still settles below.
        }
        queryClient.clear();
        setToken(null);
        setUser(null);
        setStatus("signed-out");
        setSigningOut(false);
      }
    })();
  }, [signingOut, token, authApi, storage, queryClient]);

  const handleAuthenticated = (session: Session) => {
    void (async () => {
      await storage.set(session.token);
      queryClient.clear();
      setToken(session.token);
      setUser(session.user);
      setStatus("signed-in");
    })();
  };

  const todoApi = createAuthenticatedApi(() => token, signOut, transport);

  if (status === "unknown") {
    return (
      <View style={styles.center}>
        <Text style={styles.status}>Loading…</Text>
      </View>
    );
  }

  if (status === "signed-out") {
    return (
      <AuthScreen
        signup={authApi.signup}
        login={authApi.login}
        onAuthenticated={handleAuthenticated}
      />
    );
  }

  return (
    <View style={styles.signedIn}>
      <View style={styles.header}>
        <Text style={styles.username}>Signed in as {user?.username}</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Sign out"
          style={styles.signOutButton}
          onPress={signOut}
        >
          <Text style={styles.signOutButtonText}>Sign out</Text>
        </Pressable>
      </View>
      <TodoScreen api={todoApi} />
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    alignItems: "center",
    flex: 1,
    justifyContent: "center",
  },
  status: {
    color: "#42526b",
    fontSize: 15,
  },
  signedIn: {
    flex: 1,
  },
  header: {
    alignItems: "center",
    flexDirection: "row",
    gap: 12,
    justifyContent: "space-between",
    paddingHorizontal: 24,
    paddingVertical: 8,
  },
  username: {
    color: "#42526b",
    flex: 1,
    fontSize: 15,
    fontWeight: "600",
  },
  signOutButton: {
    alignItems: "center",
    borderColor: "#aeb9c9",
    borderRadius: 10,
    borderWidth: 1,
    justifyContent: "center",
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 16,
  },
  signOutButtonText: {
    color: "#173da0",
    fontSize: 16,
    fontWeight: "700",
  },
});
