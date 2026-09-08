import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { useQueryClient } from "@tanstack/react-query";
import { TodoExperience } from "../TodoExperience";
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

type SessionIdentity = { token: string; userId: string };

export type SessionEpochControls = {
  sessionEpoch: number;
  isSessionCurrent: (epoch: number) => boolean;
};

/**
 * Opaque authentication-session era for the workflow shell. The epoch
 * changes on restore, login, logout, and replacement; workflow callbacks
 * capture it before persisting a pending write and recheck it before
 * touching cache, selection, or the pending record. Bearer tokens never
 * enter workflow storage — this context carries only the era counter.
 */
export const SessionEpochContext = createContext<SessionEpochControls>({
  sessionEpoch: 0,
  isSessionCurrent: () => false,
});

export function useSessionEpoch(): SessionEpochControls {
  return useContext(SessionEpochContext);
}

export function AuthProvider({
  authApi = defaultAuthApi,
  storage = tokenStorage,
  transport = defaultTransport,
  children,
}: {
  authApi?: ProviderAuthApi;
  storage?: TokenStorage;
  transport?: TodoTransport;
  children?: ReactNode;
} = {}): React.JSX.Element {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status>("unknown");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const liveRef = useRef<SessionIdentity | null>(null);
  const epochRef = useRef(0);
  const [sessionEpoch, setSessionEpoch] = useState(0);

  const bumpEpoch = useCallback(() => {
    epochRef.current += 1;
    setSessionEpoch(epochRef.current);
  }, []);

  const isSessionCurrent = useCallback(
    (epoch: number) => epoch === epochRef.current,
    []
  );

  const epochControls = useMemo(
    () => ({ sessionEpoch, isSessionCurrent }),
    [sessionEpoch, isSessionCurrent]
  );

  useEffect(() => {
    let mounted = true;
    void (async () => {
      let stored: string | null;
      try {
        stored = await storage.get();
      } catch {
        if (mounted) {
          bumpEpoch();
          setStatus("signed-out");
        }
        return;
      }
      if (!mounted) return;
      if (stored === null) {
        bumpEpoch();
        setStatus("signed-out");
        return;
      }
      try {
        const restored = await authApi.fetchMe({ token: stored });
        if (!mounted) return;
        liveRef.current = { token: stored, userId: restored.id };
        setUser(restored);
        bumpEpoch();
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
        bumpEpoch();
        setStatus("signed-out");
      }
    })();
    return () => {
      mounted = false;
    };
  }, [authApi, storage, bumpEpoch]);

  const cleanupSession = useCallback(
    async (captured: SessionIdentity) => {
      try {
        await authApi.logout({ token: captured.token });
      } catch {
        // Best effort: local state clears regardless of server reachability.
      }
      if (liveRef.current?.token !== captured.token) {
        // Superseded: a newer session owns the state; leave it alone.
        return;
      }
      liveRef.current = null;
      bumpEpoch();
      try {
        await storage.clear();
      } catch {
        // Best effort: local state still settles below.
      }
      queryClient.clear();
      setUser(null);
      setStatus("signed-out");
    },
    [authApi, storage, queryClient, bumpEpoch]
  );

  const signOut = useCallback(() => {
    const live = liveRef.current;
    if (signingOut || live === null) return;
    setSigningOut(true);
    void cleanupSession(live).finally(() => setSigningOut(false));
  }, [signingOut, cleanupSession]);

  const handleAuthRequired = useCallback(
    (requestToken: string | null) => {
      const live = liveRef.current;
      if (signingOut || live === null || requestToken !== live.token) return;
      setSigningOut(true);
      void cleanupSession(live).finally(() => setSigningOut(false));
    },
    [signingOut, cleanupSession]
  );

  const handleAuthenticated = (session: Session) => {
    if (signingOut) return;
    bumpEpoch();
    void (async () => {
      await storage.set(session.token);
      queryClient.clear();
      liveRef.current = { token: session.token, userId: session.user.id };
      setUser(session.user);
      setStatus("signed-in");
    })();
  };

  // eslint-disable-next-line react-hooks/refs -- both closures read identity at call time (query/event), never during render
  const todoApi = createAuthenticatedApi(() => liveRef.current?.token ?? null, handleAuthRequired, transport);

  if (status === "unknown") {
    return (
      <SessionEpochContext.Provider value={epochControls}>
        {children}
        <View style={styles.center}>
          <Text style={styles.status}>Loading…</Text>
        </View>
      </SessionEpochContext.Provider>
    );
  }

  if (status === "signed-out" || user === null) {
    return (
      <SessionEpochContext.Provider value={epochControls}>
        {children}
        <AuthScreen
          signup={authApi.signup}
          login={authApi.login}
          onAuthenticated={handleAuthenticated}
        />
      </SessionEpochContext.Provider>
    );
  }

  return (
    <SessionEpochContext.Provider value={epochControls}>
      {children}
      <View style={styles.signedIn}>
        <View style={styles.header}>
          <Text style={styles.username}>Signed in as {user.username}</Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Sign out"
            style={styles.signOutButton}
            onPress={signOut}
          >
            <Text style={styles.signOutButtonText}>Sign out</Text>
          </Pressable>
        </View>
        <TodoExperience userId={user.id} api={todoApi} />
      </View>
    </SessionEpochContext.Provider>
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
