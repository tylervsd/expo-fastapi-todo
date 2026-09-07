import * as mockReact from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { TodoApiError, type AuthUser, type Session } from "../todos/todoApi";
import { AuthScreen } from "./AuthScreen";

jest.mock("react-native", () => {
  const actual = jest.requireActual("react-native");
  const TestPressable = (props: Record<string, unknown>) =>
    mockReact.createElement("View", {
      ...props,
      accessible: true,
      accessibilityState:
        props.disabled === undefined
          ? props.accessibilityState
          : { ...(props.accessibilityState as Record<string, unknown>), disabled: props.disabled },
    });
  TestPressable.displayName = "TestPressable";
  return new Proxy(actual, {
    get(target, property, receiver) {
      if (property === "Pressable") return TestPressable;
      return Reflect.get(target, property, receiver);
    },
  });
});

const user: AuthUser = { id: "6fc33b84-16a8-4d8e-ae94-fc50bb457d72", username: "alice" };
const session: Session = {
  token: "tok-1",
  expires_at: "2026-10-07T00:00:00+00:00",
  user,
};

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
};

const setup = async (overrides?: {
  signup?: jest.Mock;
  login?: jest.Mock;
  onAuthenticated?: jest.Mock;
}) => {
  const signup = overrides?.signup ?? jest.fn(async () => user);
  const login = overrides?.login ?? jest.fn(async () => session);
  const onAuthenticated = overrides?.onAuthenticated ?? jest.fn();
  await render(<AuthScreen signup={signup} login={login} onAuthenticated={onAuthenticated} />);
  return { signup, login, onAuthenticated };
};

it("renders sign-in form with a create-account toggle", async () => {
  await setup();

  expect(screen.getByLabelText("Username")).toBeTruthy();
  expect(screen.getByLabelText("Password")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Sign in" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "New here? Create an account." })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Create account" })).toBeNull();

  await fireEvent.press(screen.getByRole("button", { name: "New here? Create an account." }));

  expect(screen.getByRole("button", { name: "Create account" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Have an account? Sign in." })).toBeTruthy();
});

it("shows local copy for empty fields without a request", async () => {
  const { login, signup } = await setup();

  await fireEvent.press(screen.getByRole("button", { name: "Sign in" }));

  expect(screen.getByRole("alert")).toHaveTextContent("Enter a username and password.");
  expect(login).not.toHaveBeenCalled();
  expect(signup).not.toHaveBeenCalled();
});

it("gates double submit to one login and reports success", async () => {
  const pending = deferred<Session>();
  const login = jest.fn(() => pending.promise);
  const onAuthenticated = jest.fn();
  await setup({ login, onAuthenticated });

  await fireEvent.changeText(screen.getByLabelText("Username"), "alice");
  await fireEvent.changeText(screen.getByLabelText("Password"), "long-enough-password");
  const button = screen.getByRole("button", { name: "Sign in" });
  const press = button.props.onPress as () => void;
  await act(async () => {
    press();
    press();
  });

  expect(login).toHaveBeenCalledTimes(1);
  expect(login).toHaveBeenCalledWith("alice", "long-enough-password");
  await act(async () => {
    pending.resolve(session);
  });
  await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith(session));
});

it("maps login 401 to the safe copy and keeps the draft", async () => {
  const login = jest.fn(async () => {
    throw new TodoApiError("auth-required", "Invalid username or password.");
  });
  await setup({ login });

  await fireEvent.changeText(screen.getByLabelText("Username"), "alice");
  await fireEvent.changeText(screen.getByLabelText("Password"), "wrong-password-ok");
  await fireEvent.press(screen.getByRole("button", { name: "Sign in" }));

  expect(screen.getByRole("alert")).toHaveTextContent("Invalid username or password.");
  expect(screen.getByLabelText("Username")).toHaveProp("value", "alice");
  expect(screen.getByLabelText("Password")).toHaveProp("value", "wrong-password-ok");
});

it("maps signup validation to the account copy", async () => {
  const signup = jest.fn(async () => {
    throw new TodoApiError("validation", "Check the username and password and try again.");
  });
  await setup({ signup });

  await fireEvent.press(screen.getByRole("button", { name: "New here? Create an account." }));
  await fireEvent.changeText(screen.getByLabelText("Username"), "al");
  await fireEvent.changeText(screen.getByLabelText("Password"), "long-enough-password");
  await fireEvent.press(screen.getByRole("button", { name: "Create account" }));

  expect(signup).toHaveBeenCalledWith("al", "long-enough-password");
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Check the username and password and try again."
  );
});

it("routes signup success through explicit sign-in", async () => {
  const signup = jest.fn(async () => user);
  const login = jest.fn(async () => session);
  const onAuthenticated = jest.fn();
  await setup({ signup, login, onAuthenticated });

  await fireEvent.press(screen.getByRole("button", { name: "New here? Create an account." }));
  await fireEvent.changeText(screen.getByLabelText("Username"), "alice");
  await fireEvent.changeText(screen.getByLabelText("Password"), "long-enough-password");
  await fireEvent.press(screen.getByRole("button", { name: "Create account" }));

  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("Account created. Please sign in.")
  );
  expect(onAuthenticated).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Username")).toHaveProp("value", "alice");
  expect(screen.getByLabelText("Password")).toHaveProp("value", "");

  await fireEvent.changeText(screen.getByLabelText("Password"), "long-enough-password");
  await fireEvent.press(screen.getByRole("button", { name: "Sign in" }));
  await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith(session));
});
