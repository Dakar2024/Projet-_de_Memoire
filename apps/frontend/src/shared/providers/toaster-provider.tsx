
import { Toaster } from "@/shared/components/ui/sonner";

export function ToasterProvider() {
  return (
    <Toaster
      position="top-center"
      toastOptions={{
        duration: 5000,
        unstyled: true,
        className:
          "flex items-center gap-3 p-4 rounded-xl text-white font-medium text-sm",
        classNames: {
          success: "bg-emerald-700 border border-emerald-600",
          error: "bg-[#ca2a30]",
          info: "bg-blue-500 border border-blue-600",
          warning: "bg-yellow-500 text-black border border-yellow-600",
        },
      }}
    />
  );
}
