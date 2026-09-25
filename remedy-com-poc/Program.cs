using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using Microsoft.Win32;

namespace RemedyComPoc
{
    internal static class Program
    {
        private static readonly string[] Keywords = { "remedy", "bmc", "ar system", "aruser" };
        private static readonly string[] InterestingMemberWords = { "openform", "form", "field", "value", "search", "modify", "create", "macro", "guide" };

        [STAThread]
        private static int Main(string[] args)
        {
            var options = Options.Parse(args);

            Console.WriteLine("=== Remedy COM proof of concept ===");
            Console.WriteLine("Step 1: scanning COM registrations");

            var candidates = FindCandidates();
            if (candidates.Count == 0)
            {
                Console.WriteLine("No COM registrations matched Remedy/BMC/AR System/ARUSER.");
                return 1;
            }

            PrintCandidates(candidates);

            var filtered = FilterCandidates(candidates, options.ProgId, options.Clsid);
            if (filtered.Count == 0)
            {
                Console.WriteLine("No discovered candidate matched the requested --progid/--clsid filter.");
                return 1;
            }

            Console.WriteLine();
            Console.WriteLine("Step 2: attempting COM attachment");

            object app = null;
            ComCandidate connectedCandidate = null;
            foreach (var candidate in filtered)
            {
                if (!TryConnect(candidate, options.AllowCreateInstance, out app))
                {
                    continue;
                }

                connectedCandidate = candidate;
                break;
            }

            if (app == null)
            {
                Console.WriteLine("Failed to connect to any discovered candidate.");
                return 1;
            }

            Console.WriteLine("SUCCESS: connected to Remedy COM");
            Console.WriteLine("Connected candidate:");
            Console.WriteLine("  ProgID discovered: " + NullText(connectedCandidate.ProgId));
            Console.WriteLine("  CLSID discovered: " + NullText(connectedCandidate.Clsid));
            Console.WriteLine("  TypeLib discovered: " + NullText(connectedCandidate.TypeLibId));

            Console.WriteLine();
            Console.WriteLine("Step 3: inspecting COM surface");
            PrintRuntimeMembers(app.GetType(), "Application object");
            InspectTypeLibrary(connectedCandidate);

            if (string.IsNullOrWhiteSpace(options.FormName))
            {
                Console.WriteLine();
                Console.WriteLine("No --form value supplied, so the tool stops after discovery/inspection.");
                return 0;
            }

            Console.WriteLine();
            Console.WriteLine("Step 4: trying OpenForm");
            object window;
            if (!TryOpenForm(app, options.FormName, out window))
            {
                return 1;
            }

            Console.WriteLine("FORM OPEN SUCCESS");
            Console.WriteLine("Returned COM type: " + window.GetType().FullName);

            Console.WriteLine();
            Console.WriteLine("Returned window/object inspection");
            PrintRuntimeMembers(window.GetType(), "Returned form/window");

            if (options.FieldId.HasValue)
            {
                Console.WriteLine();
                Console.WriteLine("Step 5: trying to read a field");
                TryFieldRead(window, options.FieldId.Value);

                if (options.SetValue != null)
                {
                    Console.WriteLine();
                    Console.WriteLine("Step 6: trying to set a field without saving");
                    TryFieldSet(window, options.FieldId.Value, options.SetValue);
                }
            }

            Console.WriteLine();
            Console.WriteLine("Done.");
            return 0;
        }

        private static List<ComCandidate> FindCandidates()
        {
            var results = new Dictionary<string, ComCandidate>(StringComparer.OrdinalIgnoreCase);
            foreach (var view in new[] { RegistryView.Registry32, RegistryView.Registry64 })
            {
                ScanClsidHive(view, results);
            }

            return results.Values
                .OrderBy(c => RegistryViewPreference(c.RegistryView))
                .ThenBy(c => c.ProgId ?? string.Empty, StringComparer.OrdinalIgnoreCase)
                .ThenBy(c => c.Clsid ?? string.Empty, StringComparer.OrdinalIgnoreCase)
                .ToList();
        }

        private static void ScanClsidHive(RegistryView view, IDictionary<string, ComCandidate> results)
        {
            try
            {
                using (var root = RegistryKey.OpenBaseKey(RegistryHive.ClassesRoot, view))
                using (var clsidRoot = root.OpenSubKey("CLSID"))
                {
                    if (clsidRoot == null)
                    {
                        return;
                    }

                    foreach (var clsid in clsidRoot.GetSubKeyNames())
                    {
                        using (var clsidKey = clsidRoot.OpenSubKey(clsid))
                        {
                            if (clsidKey == null)
                            {
                                continue;
                            }

                            var candidate = ReadCandidate(view, clsid, clsidKey);
                            if (!CandidateMatches(candidate))
                            {
                                continue;
                            }

                            results[view + "|" + clsid] = candidate;
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine("Registry scan failed for " + view + ": " + ex);
            }
        }

        private static ComCandidate ReadCandidate(RegistryView view, string clsid, RegistryKey clsidKey)
        {
            return new ComCandidate
            {
                RegistryView = view,
                Clsid = clsid,
                Description = ReadDefaultValue(clsidKey),
                ProgId = ReadDefaultValue(clsidKey.OpenSubKey("ProgID")),
                VersionIndependentProgId = ReadDefaultValue(clsidKey.OpenSubKey("VersionIndependentProgID")),
                TypeLibId = ReadDefaultValue(clsidKey.OpenSubKey("TypeLib")),
                LocalServer32 = ReadDefaultValue(clsidKey.OpenSubKey("LocalServer32")),
                InprocServer32 = ReadDefaultValue(clsidKey.OpenSubKey("InprocServer32"))
            };
        }

        private static bool CandidateMatches(ComCandidate candidate)
        {
            foreach (var value in candidate.AllTextValues())
            {
                if (ContainsKeyword(value))
                {
                    return true;
                }
            }

            return false;
        }

        private static bool ContainsKeyword(string value)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                return false;
            }

            return Keywords.Any(k => value.IndexOf(k, StringComparison.OrdinalIgnoreCase) >= 0);
        }

        private static string ReadDefaultValue(RegistryKey key)
        {
            if (key == null)
            {
                return null;
            }

            try
            {
                return key.GetValue(null) as string;
            }
            finally
            {
                key.Close();
            }
        }

        private static void PrintCandidates(IEnumerable<ComCandidate> candidates)
        {
            int index = 1;
            foreach (var candidate in candidates)
            {
                Console.WriteLine();
                Console.WriteLine("Candidate " + index++);
                Console.WriteLine("  Registry view: " + candidate.RegistryView);
                Console.WriteLine("  ProgID discovered: " + NullText(candidate.ProgId));
                Console.WriteLine("  VersionIndependentProgID: " + NullText(candidate.VersionIndependentProgId));
                Console.WriteLine("  CLSID discovered: " + NullText(candidate.Clsid));
                Console.WriteLine("  TypeLib discovered: " + NullText(candidate.TypeLibId));
                Console.WriteLine("  Description: " + NullText(candidate.Description));
                Console.WriteLine("  LocalServer32: " + NullText(candidate.LocalServer32));
                Console.WriteLine("  InprocServer32: " + NullText(candidate.InprocServer32));
            }
        }

        private static List<ComCandidate> FilterCandidates(List<ComCandidate> candidates, string progId, string clsid)
        {
            IEnumerable<ComCandidate> filtered = candidates;

            if (!string.IsNullOrWhiteSpace(progId))
            {
                filtered = filtered.Where(c =>
                    string.Equals(c.ProgId, progId, StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(c.VersionIndependentProgId, progId, StringComparison.OrdinalIgnoreCase));
            }

            if (!string.IsNullOrWhiteSpace(clsid))
            {
                filtered = filtered.Where(c => string.Equals(c.Clsid, clsid, StringComparison.OrdinalIgnoreCase));
            }

            return filtered
                .OrderBy(c => RegistryViewPreference(c.RegistryView))
                .ThenBy(c => c.ProgId ?? string.Empty, StringComparer.OrdinalIgnoreCase)
                .ThenBy(c => c.Clsid ?? string.Empty, StringComparer.OrdinalIgnoreCase)
                .ToList();
        }

        private static int RegistryViewPreference(RegistryView view)
        {
            var preferred = Environment.Is64BitProcess ? RegistryView.Registry64 : RegistryView.Registry32;
            return view == preferred ? 0 : 1;
        }

        private static bool TryConnect(ComCandidate candidate, bool allowCreateInstance, out object app)
        {
            app = null;
            var identities = new[] { candidate.ProgId, candidate.VersionIndependentProgId, candidate.Clsid }
                .Where(v => !string.IsNullOrWhiteSpace(v))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList();

            foreach (var identity in identities)
            {
                if (!identity.StartsWith("{", StringComparison.Ordinal))
                {
                    try
                    {
                        Console.WriteLine("Trying GetActiveObject(\"" + identity + "\")");
                        app = GetRunningObject(identity);
                        Console.WriteLine("Attached to running instance via GetActiveObject.");
                        return true;
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine("GetActiveObject failed: " + ex.GetType().FullName + " - " + ex.Message);
                    }

                    if (!allowCreateInstance)
                    {
                        continue;
                    }

                    try
                    {
                        Console.WriteLine("Trying Activator.CreateInstance(Type.GetTypeFromProgID(\"" + identity + "\"))");
                        var type = Type.GetTypeFromProgID(identity, false);
                        if (type == null)
                        {
                            Console.WriteLine("Type.GetTypeFromProgID returned null.");
                        }
                        else
                        {
                            app = Activator.CreateInstance(type);
                            Console.WriteLine("Created COM instance via ProgID.");
                            return true;
                        }
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine("CreateInstance via ProgID failed: " + ex);
                    }
                }

                Guid guid;
                if (!Guid.TryParse(identity, out guid))
                {
                    continue;
                }

                if (!allowCreateInstance)
                {
                    continue;
                }

                try
                {
                    Console.WriteLine("Trying Activator.CreateInstance(Type.GetTypeFromCLSID(\"" + guid + "\"))");
                    var type = Type.GetTypeFromCLSID(guid, false);
                    if (type == null)
                    {
                        Console.WriteLine("Type.GetTypeFromCLSID returned null.");
                    }
                    else
                    {
                        app = Activator.CreateInstance(type);
                        Console.WriteLine("Created COM instance via CLSID.");
                        return true;
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine("CreateInstance via CLSID failed: " + ex);
                }
            }

            return false;
        }

        private static void PrintRuntimeMembers(Type type, string title)
        {
            Console.WriteLine(title + ": " + type.FullName);
            var methods = type.GetMethods(BindingFlags.Instance | BindingFlags.Public)
                .Where(m => !m.IsSpecialName)
                .OrderBy(m => m.Name, StringComparer.OrdinalIgnoreCase)
                .ToList();
            var properties = type.GetProperties(BindingFlags.Instance | BindingFlags.Public)
                .OrderBy(p => p.Name, StringComparer.OrdinalIgnoreCase)
                .ToList();

            Console.WriteLine("Properties:");
            if (properties.Count == 0)
            {
                Console.WriteLine("  (none)");
            }
            else
            {
                foreach (var property in properties)
                {
                    Console.WriteLine("  " + FriendlyTypeName(property.PropertyType) + " " + property.Name);
                }
            }

            Console.WriteLine("Methods:");
            if (methods.Count == 0)
            {
                Console.WriteLine("  (none)");
            }
            else
            {
                foreach (var method in methods)
                {
                    var line = "  " + FormatMethod(method);
                    if (IsInterestingName(method.Name))
                    {
                        line += "   <-- interesting";
                    }

                    Console.WriteLine(line);
                }
            }
        }

        private static bool IsInterestingName(string name)
        {
            return InterestingMemberWords.Any(word => name.IndexOf(word, StringComparison.OrdinalIgnoreCase) >= 0);
        }

        private static string FormatMethod(MethodInfo method)
        {
            var parameters = method.GetParameters()
                .Select(p => FriendlyTypeName(p.ParameterType) + " " + p.Name + (p.IsOptional ? " = Missing" : string.Empty));
            return FriendlyTypeName(method.ReturnType) + " " + method.Name + "(" + string.Join(", ", parameters) + ")";
        }

        private static string FriendlyTypeName(Type type)
        {
            if (type == null)
            {
                return "void";
            }

            if (type == typeof(void))
            {
                return "void";
            }

            if (!type.IsGenericType)
            {
                return type.Name;
            }

            var genericName = type.Name;
            var tickIndex = genericName.IndexOf('`');
            if (tickIndex >= 0)
            {
                genericName = genericName.Substring(0, tickIndex);
            }

            return genericName + "<" + string.Join(", ", type.GetGenericArguments().Select(FriendlyTypeName)) + ">";
        }

        private static void InspectTypeLibrary(ComCandidate candidate)
        {
            if (string.IsNullOrWhiteSpace(candidate.TypeLibId))
            {
                Console.WriteLine("No TypeLib found on the connected CLSID.");
                return;
            }

            Console.WriteLine("Type library inspection:");
            foreach (var version in FindTypeLibVersions(candidate.RegistryView, candidate.TypeLibId))
            {
                Console.WriteLine("  Found TypeLib version " + version.VersionText + " (" + version.RegistryView + ")");
                ITypeLib typeLib = null;

                try
                {
                    var guid = new Guid(candidate.TypeLibId);
                    typeLib = LoadRegisteredTypeLib(guid, version.Major, version.Minor);
                    if (typeLib == null)
                    {
                        Console.WriteLine("    LoadRegTypeLib returned null.");
                        continue;
                    }

                    string libName;
                    string docString;
                    int helpContext;
                    string helpFile;
                    typeLib.GetDocumentation(-1, out libName, out docString, out helpContext, out helpFile);
                    Console.WriteLine("    Name: " + NullText(libName));

                    var interfaceNames = new List<string>();
                    int typeCount = typeLib.GetTypeInfoCount();
                    for (int i = 0; i < typeCount; i++)
                    {
                        TYPEKIND kind;
                        typeLib.GetTypeInfoType(i, out kind);

                        ITypeInfo typeInfo;
                        typeLib.GetTypeInfo(i, out typeInfo);

                        string typeName;
                        string typeDoc;
                        int typeHelpContext;
                        string typeHelpFile;
                        typeInfo.GetDocumentation(-1, out typeName, out typeDoc, out typeHelpContext, out typeHelpFile);
                        interfaceNames.Add(typeName + " [" + kind + "]");

                        bool dumpMembers =
                            typeName.IndexOf("icomapp", StringComparison.OrdinalIgnoreCase) >= 0 ||
                            typeName.IndexOf("ischemawnd", StringComparison.OrdinalIgnoreCase) >= 0 ||
                            typeName.IndexOf("form", StringComparison.OrdinalIgnoreCase) >= 0 ||
                            typeName.IndexOf("field", StringComparison.OrdinalIgnoreCase) >= 0;

                        Console.WriteLine("    Type: " + typeName + " [" + kind + "]");
                        if (dumpMembers)
                        {
                            DumpTypeInfoMembers(typeInfo);
                        }

                        Marshal.ReleaseComObject(typeInfo);
                    }

                    Console.WriteLine("    COM interface names: " + string.Join(", ", interfaceNames));
                }
                catch (Exception ex)
                {
                    Console.WriteLine("    TypeLib inspection failed: " + ex);
                }
                finally
                {
                    if (typeLib != null)
                    {
                        Marshal.ReleaseComObject(typeLib);
                    }
                }
            }
        }

        private static IEnumerable<TypeLibVersion> FindTypeLibVersions(RegistryView preferredView, string typeLibId)
        {
            var versions = new List<TypeLibVersion>();
            foreach (var view in new[] { preferredView })
            {
                try
                {
                    using (var root = RegistryKey.OpenBaseKey(RegistryHive.ClassesRoot, view))
                    using (var typeLibRoot = root.OpenSubKey(@"TypeLib\" + typeLibId))
                    {
                        if (typeLibRoot == null)
                        {
                            continue;
                        }

                        foreach (var versionText in typeLibRoot.GetSubKeyNames())
                        {
                            ushort major;
                            ushort minor;
                            if (!TryParseVersion(versionText, out major, out minor))
                            {
                                continue;
                            }

                            versions.Add(new TypeLibVersion
                            {
                                RegistryView = view,
                                VersionText = versionText,
                                Major = major,
                                Minor = minor
                            });
                        }
                    }
                }
                catch
                {
                }
            }

            return versions
                .GroupBy(v => v.RegistryView + "|" + v.VersionText, StringComparer.OrdinalIgnoreCase)
                .Select(g => g.First())
                .OrderBy(v => v.RegistryView == preferredView ? 0 : 1)
                .ThenByDescending(v => v.Major)
                .ThenByDescending(v => v.Minor)
                .ToList();
        }

        private static bool TryParseVersion(string versionText, out ushort major, out ushort minor)
        {
            major = 0;
            minor = 0;
            if (string.IsNullOrWhiteSpace(versionText))
            {
                return false;
            }

            var parts = versionText.Split('.');
            if (parts.Length == 0 || parts.Length > 2)
            {
                return false;
            }

            ushort parsedMajor;
            if (!ushort.TryParse(parts[0], out parsedMajor))
            {
                return false;
            }

            ushort parsedMinor = 0;
            if (parts.Length == 2 && !ushort.TryParse(parts[1], out parsedMinor))
            {
                return false;
            }

            major = parsedMajor;
            minor = parsedMinor;
            return true;
        }

        private static ITypeLib LoadRegisteredTypeLib(Guid guid, ushort major, ushort minor)
        {
            ITypeLib typeLib;
            var hr = LoadRegTypeLib(ref guid, major, minor, 0, out typeLib);
            if (hr != 0)
            {
                Marshal.ThrowExceptionForHR(hr);
            }

            return typeLib;
        }

        private static void DumpTypeInfoMembers(ITypeInfo typeInfo)
        {
            IntPtr typeAttrPtr = IntPtr.Zero;

            try
            {
                typeInfo.GetTypeAttr(out typeAttrPtr);
                var typeAttr = (TYPEATTR)Marshal.PtrToStructure(typeAttrPtr, typeof(TYPEATTR));

                for (int i = 0; i < typeAttr.cFuncs; i++)
                {
                    IntPtr funcDescPtr = IntPtr.Zero;
                    try
                    {
                        typeInfo.GetFuncDesc(i, out funcDescPtr);
                        var funcDesc = (FUNCDESC)Marshal.PtrToStructure(funcDescPtr, typeof(FUNCDESC));
                        Console.WriteLine("      " + BuildTypeInfoSignature(typeInfo, funcDesc));
                    }
                    finally
                    {
                        if (funcDescPtr != IntPtr.Zero)
                        {
                            typeInfo.ReleaseFuncDesc(funcDescPtr);
                        }
                    }
                }
            }
            finally
            {
                if (typeAttrPtr != IntPtr.Zero)
                {
                    typeInfo.ReleaseTypeAttr(typeAttrPtr);
                }
            }
        }

        private static string BuildTypeInfoSignature(ITypeInfo typeInfo, FUNCDESC funcDesc)
        {
            int nameCount;
            var names = new string[funcDesc.cParams + 1];
            typeInfo.GetNames(funcDesc.memid, names, names.Length, out nameCount);
            var methodName = nameCount > 0 ? names[0] : "MEMBER_" + funcDesc.memid;

            var parameters = new List<string>();
            var elementSize = Marshal.SizeOf(typeof(ELEMDESC));

            for (int i = 0; i < funcDesc.cParams; i++)
            {
                var elementPtr = new IntPtr(funcDesc.lprgelemdescParam.ToInt64() + (i * elementSize));
                var element = (ELEMDESC)Marshal.PtrToStructure(elementPtr, typeof(ELEMDESC));
                var paramName = i + 1 < nameCount ? names[i + 1] : "arg" + i;
                parameters.Add(DescribeTypeDesc(typeInfo, element.tdesc) + " " + paramName);
            }

            return DescribeTypeDesc(typeInfo, funcDesc.elemdescFunc.tdesc) + " " + methodName + "(" + string.Join(", ", parameters) + ")" + DescribeInvokeKind(funcDesc.invkind);
        }

        private static string DescribeInvokeKind(INVOKEKIND invokeKind)
        {
            switch (invokeKind)
            {
                case INVOKEKIND.INVOKE_FUNC:
                    return string.Empty;
                case INVOKEKIND.INVOKE_PROPERTYGET:
                    return " [propget]";
                case INVOKEKIND.INVOKE_PROPERTYPUT:
                    return " [propput]";
                case INVOKEKIND.INVOKE_PROPERTYPUTREF:
                    return " [propputref]";
                default:
                    return " [" + invokeKind + "]";
            }
        }

        private static string DescribeTypeDesc(ITypeInfo typeInfo, TYPEDESC typeDesc)
        {
            var vt = (VarEnum)typeDesc.vt;
            switch (vt)
            {
                case VarEnum.VT_EMPTY: return "EMPTY";
                case VarEnum.VT_NULL: return "NULL";
                case VarEnum.VT_I2: return "short";
                case VarEnum.VT_I4: return "int";
                case VarEnum.VT_R4: return "float";
                case VarEnum.VT_R8: return "double";
                case VarEnum.VT_CY: return "CURRENCY";
                case VarEnum.VT_DATE: return "DATE";
                case VarEnum.VT_BSTR: return "BSTR";
                case VarEnum.VT_DISPATCH: return "IDispatch";
                case VarEnum.VT_ERROR: return "SCODE";
                case VarEnum.VT_BOOL: return "VARIANT_BOOL";
                case VarEnum.VT_VARIANT: return "VARIANT";
                case VarEnum.VT_UNKNOWN: return "IUnknown";
                case VarEnum.VT_DECIMAL: return "DECIMAL";
                case VarEnum.VT_I1: return "sbyte";
                case VarEnum.VT_UI1: return "byte";
                case VarEnum.VT_UI2: return "ushort";
                case VarEnum.VT_UI4: return "uint";
                case VarEnum.VT_I8: return "long";
                case VarEnum.VT_UI8: return "ulong";
                case VarEnum.VT_INT: return "int";
                case VarEnum.VT_UINT: return "uint";
                case VarEnum.VT_VOID: return "void";
                case VarEnum.VT_HRESULT: return "HRESULT";
                case VarEnum.VT_LPSTR: return "LPSTR";
                case VarEnum.VT_LPWSTR: return "LPWSTR";
                case VarEnum.VT_PTR:
                    return DescribeTypeDesc(typeInfo, (TYPEDESC)Marshal.PtrToStructure(typeDesc.lpValue, typeof(TYPEDESC))) + "*";
                case VarEnum.VT_SAFEARRAY:
                    return "SAFEARRAY(" + DescribeTypeDesc(typeInfo, (TYPEDESC)Marshal.PtrToStructure(typeDesc.lpValue, typeof(TYPEDESC))) + ")";
                case VarEnum.VT_USERDEFINED:
                    try
                    {
                        ITypeInfo refTypeInfo;
                        typeInfo.GetRefTypeInfo(ReadHrefType(typeDesc.lpValue), out refTypeInfo);
                        string refName;
                        string refDoc;
                        int refHelpContext;
                        string refHelpFile;
                        refTypeInfo.GetDocumentation(-1, out refName, out refDoc, out refHelpContext, out refHelpFile);
                        Marshal.ReleaseComObject(refTypeInfo);
                        return refName;
                    }
                    catch
                    {
                        return "USERDEFINED(" + typeDesc.lpValue.ToInt64() + ")";
                    }
                default:
                    return vt.ToString();
            }
        }

        private static bool TryOpenForm(object app, string formName, out object window)
        {
            window = null;
            var method = app.GetType()
                .GetMethods(BindingFlags.Instance | BindingFlags.Public)
                .FirstOrDefault(m => string.Equals(m.Name, "OpenForm", StringComparison.OrdinalIgnoreCase));

            if (method == null)
            {
                Console.WriteLine("OpenForm was not exposed on the runtime COM type.");
                return false;
            }

            Console.WriteLine("OpenForm signature: " + FormatMethod(method));
            var args = BuildOpenFormArguments(method, formName);
            if (args == null)
            {
                Console.WriteLine("Could not safely auto-build OpenForm arguments from the discovered signature.");
                return false;
            }

            try
            {
                window = method.Invoke(app, args);
                return true;
            }
            catch (TargetInvocationException ex)
            {
                Console.WriteLine("OpenForm failed: " + (ex.InnerException ?? ex));
                return false;
            }
            catch (Exception ex)
            {
                Console.WriteLine("OpenForm failed: " + ex);
                return false;
            }
        }

        private static object[] BuildOpenFormArguments(MethodInfo method, string formName)
        {
            var parameters = method.GetParameters();
            if (parameters.Length == 0)
            {
                return Array.Empty<object>();
            }

            var args = new object[parameters.Length];
            var formAssigned = false;

            for (int i = 0; i < parameters.Length; i++)
            {
                var parameter = parameters[i];
                if (!formAssigned && parameter.ParameterType == typeof(string))
                {
                    args[i] = formName;
                    formAssigned = true;
                    continue;
                }

                if (parameter.IsOptional)
                {
                    args[i] = Type.Missing;
                    continue;
                }

                return null;
            }

            return formAssigned ? args : null;
        }

        private static void TryFieldRead(object window, int fieldId)
        {
            foreach (var method in FindInterestingFieldMethods(window.GetType()))
            {
                if (method.GetParameters().Length != 1)
                {
                    continue;
                }

                var parameter = method.GetParameters()[0];
                if (!CanUseFieldIdentifier(parameter.ParameterType))
                {
                    continue;
                }

                try
                {
                    var value = method.Invoke(window, new[] { ConvertFieldIdentifier(parameter.ParameterType, fieldId) });
                    Console.WriteLine("field-read method: " + FormatMethod(method));
                    Console.WriteLine("FIELD READ SUCCESS");
                    Console.WriteLine("Field: " + fieldId);
                    Console.WriteLine("Value: " + (value ?? "<null>"));
                    return;
                }
                catch (Exception ex)
                {
                    Console.WriteLine("Field read attempt failed via " + method.Name + ": " + Unwrap(ex));
                }
            }

            Console.WriteLine("No successful field-read method was found automatically.");
        }

        private static void TryFieldSet(object window, int fieldId, string newValue)
        {
            foreach (var method in FindInterestingFieldMethods(window.GetType()))
            {
                var parameters = method.GetParameters();
                if (parameters.Length != 2)
                {
                    continue;
                }

                if (!CanUseFieldIdentifier(parameters[0].ParameterType))
                {
                    continue;
                }

                if (!CanAssignValue(parameters[1].ParameterType, newValue))
                {
                    continue;
                }

                try
                {
                    method.Invoke(window, new[]
                    {
                        ConvertFieldIdentifier(parameters[0].ParameterType, fieldId),
                        ConvertFieldValue(parameters[1].ParameterType, newValue)
                    });
                    Console.WriteLine("field-set method: " + FormatMethod(method));
                    Console.WriteLine("FIELD SET SUCCESS");
                    return;
                }
                catch (Exception ex)
                {
                    Console.WriteLine("Field set attempt failed via " + method.Name + ": " + Unwrap(ex));
                }
            }

            Console.WriteLine("No successful field-set method was found automatically.");
        }

        private static IEnumerable<MethodInfo> FindInterestingFieldMethods(Type type)
        {
            return type.GetMethods(BindingFlags.Instance | BindingFlags.Public)
                .Where(m => !m.IsSpecialName)
                .Where(m => InterestingMemberWords.Any(word => m.Name.IndexOf(word, StringComparison.OrdinalIgnoreCase) >= 0))
                .OrderBy(m => m.Name, StringComparer.OrdinalIgnoreCase);
        }

        private static bool CanUseFieldIdentifier(Type type)
        {
            return type == typeof(int) || type == typeof(short) || type == typeof(object) || type == typeof(string);
        }

        private static object ConvertFieldIdentifier(Type type, int fieldId)
        {
            if (type == typeof(short))
            {
                if (fieldId < short.MinValue || fieldId > short.MaxValue)
                {
                    throw new ArgumentOutOfRangeException("fieldId", fieldId, "Field ID does not fit in an Int16 parameter.");
                }

                return (short)fieldId;
            }

            if (type == typeof(string))
            {
                return fieldId.ToString();
            }

            return fieldId;
        }

        private static bool CanAssignValue(Type type, string value)
        {
            if (type == typeof(string) || type == typeof(object))
            {
                return true;
            }

            int _;
            return type == typeof(int) && int.TryParse(value, out _);
        }

        private static object ConvertFieldValue(Type type, string value)
        {
            if (type == typeof(int))
            {
                return int.Parse(value);
            }

            return value;
        }

        private static string Unwrap(Exception ex)
        {
            var tie = ex as TargetInvocationException;
            return (tie != null && tie.InnerException != null ? tie.InnerException : ex).ToString();
        }

        private static string NullText(string value)
        {
            return string.IsNullOrWhiteSpace(value) ? "<none>" : value;
        }

        private static object GetRunningObject(string progId)
        {
#if NETFRAMEWORK
            return Marshal.GetActiveObject(progId);
#else
            Guid clsid;
            var hr = CLSIDFromProgIDEx(progId, out clsid);
            if (hr != 0)
            {
                hr = CLSIDFromProgID(progId, out clsid);
                if (hr != 0)
                {
                    Marshal.ThrowExceptionForHR(hr);
                }
            }

            object activeObject;
            hr = GetActiveObject(ref clsid, IntPtr.Zero, out activeObject);
            if (hr != 0)
            {
                Marshal.ThrowExceptionForHR(hr);
            }

            return activeObject;
#endif
        }

        private static int ReadHrefType(IntPtr hrefType)
        {
            return IntPtr.Size == 4 ? hrefType.ToInt32() : unchecked((int)hrefType.ToInt64());
        }

#if !NETFRAMEWORK
        [DllImport("oleaut32.dll", PreserveSig = true)]
        private static extern int GetActiveObject(ref Guid rclsid, IntPtr reserved, [MarshalAs(UnmanagedType.Interface)] out object ppunk);

        [DllImport("ole32.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
        private static extern int CLSIDFromProgIDEx(string progId, out Guid clsid);

        [DllImport("ole32.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
        private static extern int CLSIDFromProgID(string progId, out Guid clsid);
#endif

        [DllImport("oleaut32.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
        private static extern int LoadRegTypeLib(ref Guid rguid, ushort wVerMajor, ushort wVerMinor, int lcid, out ITypeLib ppTLib);

        private sealed class ComCandidate
        {
            public RegistryView RegistryView { get; set; }
            public string Clsid { get; set; }
            public string ProgId { get; set; }
            public string VersionIndependentProgId { get; set; }
            public string TypeLibId { get; set; }
            public string Description { get; set; }
            public string LocalServer32 { get; set; }
            public string InprocServer32 { get; set; }

            public IEnumerable<string> AllTextValues()
            {
                yield return Clsid;
                yield return ProgId;
                yield return VersionIndependentProgId;
                yield return TypeLibId;
                yield return Description;
                yield return LocalServer32;
                yield return InprocServer32;
            }
        }

        private sealed class TypeLibVersion
        {
            public RegistryView RegistryView { get; set; }
            public string VersionText { get; set; }
            public ushort Major { get; set; }
            public ushort Minor { get; set; }
        }

        private sealed class Options
        {
            public string ProgId { get; private set; }
            public string Clsid { get; private set; }
            public string FormName { get; private set; }
            public int? FieldId { get; private set; }
            public string SetValue { get; private set; }
            public bool AllowCreateInstance { get; private set; }

            public static Options Parse(string[] args)
            {
                var options = new Options();
                for (int i = 0; i < args.Length; i++)
                {
                    var arg = args[i];
                    switch (arg.ToLowerInvariant())
                    {
                        case "--progid":
                            options.ProgId = NextValue(args, ref i, arg);
                            break;
                        case "--clsid":
                            options.Clsid = NextValue(args, ref i, arg);
                            break;
                        case "--form":
                            options.FormName = NextValue(args, ref i, arg);
                            break;
                        case "--field-id":
                            options.FieldId = ParseFieldId(NextValue(args, ref i, arg));
                            break;
                        case "--set-value":
                            options.SetValue = NextValue(args, ref i, arg);
                            break;
                        case "--allow-create-instance":
                            options.AllowCreateInstance = true;
                            break;
                        case "--help":
                        case "/?":
                        case "-h":
                            PrintUsageAndExit();
                            break;
                        default:
                            throw new ArgumentException("Unknown argument: " + arg);
                    }
                }

                if (options.SetValue != null && !options.FieldId.HasValue)
                {
                    throw new ArgumentException("--set-value requires --field-id.");
                }

                return options;
            }

            private static string NextValue(string[] args, ref int index, string currentArg)
            {
                if (index + 1 >= args.Length)
                {
                    throw new ArgumentException("Missing value for " + currentArg);
                }

                index++;
                return args[index];
            }

            private static int ParseFieldId(string value)
            {
                int fieldId;
                if (!int.TryParse(value, out fieldId))
                {
                    throw new ArgumentException("Invalid value for --field-id: " + value);
                }

                return fieldId;
            }

            private static void PrintUsageAndExit()
            {
                Console.WriteLine("Usage:");
                Console.WriteLine("  RemedyComPoc.exe [--progid <ProgID>] [--clsid <CLSID>] [--form <FormName>] [--field-id <id>] [--set-value <text>] [--allow-create-instance]");
                Console.WriteLine();
                Console.WriteLine("Examples:");
                Console.WriteLine("  RemedyComPoc.exe");
                Console.WriteLine("  RemedyComPoc.exe --progid Some.Discovered.ProgId --form \"HPD:Help Desk\"");
                Console.WriteLine("  RemedyComPoc.exe --progid Some.Discovered.ProgId --form \"HPD:Help Desk\" --field-id 7 --set-value \"COM TEST\"");
                Console.WriteLine("  RemedyComPoc.exe --progid Some.Discovered.ProgId --allow-create-instance");
                Environment.Exit(0);
            }
        }
    }
}
