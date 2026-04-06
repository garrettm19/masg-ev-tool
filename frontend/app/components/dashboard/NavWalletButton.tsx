"use client";

export function NavWalletButton() {
  return (
    <button
      className="font-mono text-[10px] tracking-wider uppercase px-4 py-1.5 rounded-md border transition-all duration-200"
      style={{
        color: "#2dd4bf",
        borderColor: "rgba(45,212,191,0.25)",
        background: "rgba(45,212,191,0.04)",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = "rgba(45,212,191,0.10)";
        e.currentTarget.style.borderColor = "rgba(45,212,191,0.4)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "rgba(45,212,191,0.04)";
        e.currentTarget.style.borderColor = "rgba(45,212,191,0.25)";
      }}
      disabled
    >
      Connect Wallet
    </button>
  );
}
