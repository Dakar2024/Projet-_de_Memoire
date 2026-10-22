import { clsx, type ClassValue } from 'clsx'
import { toast } from 'sonner'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function copyContent(content: any) {
  navigator.clipboard.writeText(content)
  toast.success("Copié !")
}

export interface CustomHookProps {
  state: any,
  handlers: any,
  mutations: any,
  ref: any,
  form: any
}

/**
 * Convert a FormData object to an object
 * @param formData - The FormData object to convert
 * @returns The converted object
 */
export function formDataToObject(formData: FormData) {
  const object: any = {};
  for (const [key, value] of formData.entries()) {
    object[key] = value;
  }
  return object;
}

/**
 * Convert an object to a FormData object
 * @param object - The object to convert
 * @returns The converted FormData object
 */
export function objectToFormData(object: Record<string, any>) {
  const formData = new FormData();
  for (const [key, value] of Object.entries(object)) {
    if (value instanceof File) {
      formData.append(key, value, value.name);
    } else {
      formData.append(key, value);
    }
  }
  return formData;
}