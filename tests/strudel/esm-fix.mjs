// Node resolve hook. @kabelsalat/web (a dependency of @strudel/core) declares
// its ES module build only in the "module" field, which bundlers such as Vite
// (used by strudel.cc) honour but Node ignores. Node would load the UMD
// "main" build, whose named exports it cannot see. Point it at the ESM build.
const ESM_ONLY = {
  '@kabelsalat/web': '@kabelsalat/web/dist/index.mjs',
};

export async function resolve(specifier, context, nextResolve) {
  if (Object.hasOwn(ESM_ONLY, specifier)) {
    return nextResolve(ESM_ONLY[specifier], context);
  }
  return nextResolve(specifier, context);
}
